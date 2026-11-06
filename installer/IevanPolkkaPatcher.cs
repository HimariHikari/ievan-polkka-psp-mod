// Ievan Polkka PV mod installer for "Hatsune Miku: Project DIVA" (PSP, ULJM-05472) - English patch v1.0.
// Applies the mod to the user's OWN copy of the game: reads their ISO, writes a new modded ISO next to it.
// The original ISO is never modified. Only the mod's own data is shipped (embedded resource payload.bin).
//
// Build (no installs needed, uses the C# compiler that ships with Windows):
//   C:\Windows\Microsoft.NET\Framework64\v4.0.30319\csc.exe /target:winexe /out:IevanPolkkaPatcher.exe
//     /resource:payload.bin,payload.bin /r:System.Windows.Forms.dll /r:System.Drawing.dll IevanPolkkaPatcher.cs
// Command line use:  IevanPolkkaPatcher.exe "<input.iso>" ["<output.iso>"]
using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

static class Iso
{
    public const int Sector = 2048;

    public class Rec { public long RecPos; public uint Lba; public uint Size; public bool Dir; public string Name; }

    static IEnumerable<Rec> ReadDir(Stream s, uint lba, uint size)
    {
        byte[] data = new byte[size];
        s.Position = (long)lba * Sector; ReadFully(s, data, 0, (int)size);
        int o = 0;
        while (o < data.Length)
        {
            int len = data[o];
            if (len == 0) { o = (o / Sector + 1) * Sector; continue; }
            Rec r = new Rec();
            r.RecPos = (long)lba * Sector + o;
            r.Lba = BitConverter.ToUInt32(data, o + 2);
            r.Size = BitConverter.ToUInt32(data, o + 10);
            r.Dir = (data[o + 25] & 2) != 0;
            int nlen = data[o + 32];
            string n = Encoding.ASCII.GetString(data, o + 33, nlen);
            int semi = n.IndexOf(';'); if (semi >= 0) n = n.Substring(0, semi);
            r.Name = n;
            yield return r;
            o += len;
        }
    }

    public static Rec Find(Stream s, string path)
    {
        byte[] pvd = new byte[Sector];
        s.Position = 16L * Sector; ReadFully(s, pvd, 0, Sector);
        if (Encoding.ASCII.GetString(pvd, 1, 5) != "CD001") throw new Exception("Not an ISO9660 image.");
        uint lba = BitConverter.ToUInt32(pvd, 156 + 2), size = BitConverter.ToUInt32(pvd, 156 + 10);
        Rec rec = null;
        foreach (string part in path.Split('/'))
        {
            rec = null;
            foreach (Rec r in ReadDir(s, lba, size))
                if (string.Equals(r.Name, part, StringComparison.OrdinalIgnoreCase)) { rec = r; break; }
            if (rec == null) throw new Exception("File not found in ISO: " + path);
            lba = rec.Lba; size = rec.Size;
        }
        return rec;
    }

    public static void SetExtent(Stream s, Rec r, uint lba, uint size)
    {
        byte[] b = new byte[16];
        WriteLE(b, 0, lba); WriteBE(b, 4, lba); WriteLE(b, 8, size); WriteBE(b, 12, size);
        s.Position = r.RecPos + 2; s.Write(b, 0, 16);
    }

    public static void SetVolumeSize(Stream s, uint sectors)
    {
        byte[] b = new byte[8]; WriteLE(b, 0, sectors); WriteBE(b, 4, sectors);
        s.Position = 16L * Sector + 80; s.Write(b, 0, 8);
    }

    public static void WriteLE(byte[] b, int o, uint v) { b[o] = (byte)v; b[o + 1] = (byte)(v >> 8); b[o + 2] = (byte)(v >> 16); b[o + 3] = (byte)(v >> 24); }
    public static void WriteBE(byte[] b, int o, uint v) { b[o + 3] = (byte)v; b[o + 2] = (byte)(v >> 8); b[o + 1] = (byte)(v >> 16); b[o] = (byte)(v >> 24); }

    public static void ReadFully(Stream s, byte[] b, int o, int n)
    {
        while (n > 0) { int r = s.Read(b, o, n); if (r <= 0) throw new EndOfStreamException(); o += r; n -= r; }
    }
}

class Payload
{
    public byte[] EbootSha1; public uint EbootSize;
    public uint DataCount, ScriptCount;
    public List<KeyValuePair<uint, byte[][]>> EbootPatches = new List<KeyValuePair<uint, byte[][]>>();
    public class FileRep { public int Archive; public uint Index; public byte[] OrigSha1; public byte[] Data; }
    public List<FileRep> Files = new List<FileRep>();

    public static Payload Load()
    {
        Stream res = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.bin");
        if (res == null) throw new Exception("Mod data missing from the installer.");
        byte[] magic = new byte[8]; Iso.ReadFully(res, magic, 0, 8);
        if (Encoding.ASCII.GetString(magic) != "IPMOD001") throw new Exception("Bad mod data.");
        MemoryStream ms = new MemoryStream();
        using (DeflateStream d = new DeflateStream(res, CompressionMode.Decompress)) d.CopyTo(ms);
        BinaryReader r = new BinaryReader(new MemoryStream(ms.ToArray()));
        Payload p = new Payload();
        r.ReadUInt32();
        p.EbootSha1 = r.ReadBytes(20); p.EbootSize = r.ReadUInt32();
        p.DataCount = r.ReadUInt32(); p.ScriptCount = r.ReadUInt32();
        uint np = r.ReadUInt32();
        for (uint i = 0; i < np; i++)
        {
            uint off = r.ReadUInt32(), len = r.ReadUInt32();
            byte[] oldB = r.ReadBytes((int)len), newB = r.ReadBytes((int)len);
            p.EbootPatches.Add(new KeyValuePair<uint, byte[][]>(off, new byte[][] { oldB, newB }));
        }
        uint nf = r.ReadUInt32();
        for (uint i = 0; i < nf; i++)
        {
            FileRep f = new FileRep();
            f.Archive = r.ReadByte(); f.Index = r.ReadUInt32(); f.OrigSha1 = r.ReadBytes(20);
            f.Data = r.ReadBytes((int)r.ReadUInt32());
            p.Files.Add(f);
        }
        return p;
    }
}

static class Patcher
{
    const string AfsDir = "PSP_GAME/USRDIR/media/afs/";
    const int Align = 0x800;

    public static void Run(string input, string output, Action<int, string> progress)
    {
        progress(0, "Reading mod data...");
        Payload pay = Payload.Load();

        using (FileStream src = new FileStream(input, FileMode.Open, FileAccess.Read, FileShare.Read))
        {
            progress(2, "Checking your game copy...");
            Iso.Rec eboot = Iso.Find(src, "PSP_GAME/SYSDIR/EBOOT.BIN");
            byte[] eb = ReadExtent(src, eboot);
            if (eb.Length != pay.EbootSize || !Same(Sha1(eb), pay.EbootSha1))
                throw new Exception("This ISO isn't the supported version.\n\nYou need: Hatsune Miku - Project DIVA (ULJM-05472) with the English patch v1.0 applied.\n(Its EBOOT.BIN doesn't match.)");
            Iso.Rec dataRec = Iso.Find(src, AfsDir + "DivaDataList.afs");
            Iso.Rec scrRec = Iso.Find(src, AfsDir + "DivaScriptList.afs");
            Afs data = Afs.Read(src, dataRec), scr = Afs.Read(src, scrRec);
            if (data.Count != pay.DataCount || scr.Count != pay.ScriptCount)
                throw new Exception("This ISO's data archives don't match the supported version (already modded?).");

            // replacements, verified against the original entries
            Dictionary<uint, byte[]>[] rep = { new Dictionary<uint, byte[]>(), new Dictionary<uint, byte[]>() };
            foreach (Payload.FileRep f in pay.Files)
            {
                Afs a = f.Archive == 0 ? data : scr;
                if (!Same(Sha1(a.ReadEntry(src, (int)f.Index)), f.OrigSha1))
                    throw new Exception("Game file #" + f.Index + " doesn't match the supported version (already modded?).");
                rep[f.Archive][f.Index] = f.Data;
            }
            foreach (KeyValuePair<uint, byte[][]> p in pay.EbootPatches)
                if (!Same(Slice(eb, (int)p.Key, p.Value[0].Length), p.Value[0]))
                    throw new Exception("EBOOT.BIN doesn't match the supported version (already modded?).");

            progress(5, "Copying your ISO (this takes a minute)...");
            using (FileStream dst = new FileStream(output, FileMode.Create, FileAccess.ReadWrite, FileShare.None))
            {
                Copy(src, 0, dst, 0, src.Length, delegate(double f) { progress(5 + (int)(f * 55), "Copying your ISO..."); });

                progress(60, "Patching EBOOT.BIN...");
                foreach (KeyValuePair<uint, byte[][]> p in pay.EbootPatches)
                {
                    dst.Position = (long)eboot.Lba * Iso.Sector + p.Key;
                    dst.Write(p.Value[1], 0, p.Value[1].Length);
                }

                progress(62, "Rebuilding DivaScriptList.afs...");
                MemoryStream sm = new MemoryStream();
                scr.Rebuild(src, sm, rep[1], null);
                WriteFile(dst, scrRec, sm.ToArray());

                progress(64, "Rebuilding DivaDataList.afs...");
                long end = Align2(dst.Length, Iso.Sector);
                dst.SetLength(end);
                dst.Position = end;
                long start = end;
                data.Rebuild(src, dst, rep[0], delegate(double f) { progress(64 + (int)(f * 34), "Rebuilding DivaDataList.afs..."); });
                long len = dst.Position - start;
                long padded = Align2(dst.Position, Iso.Sector);
                dst.SetLength(padded);
                Iso.SetExtent(dst, dataRec, (uint)(start / Iso.Sector), (uint)len);
                Iso.SetVolumeSize(dst, (uint)(padded / Iso.Sector));
            }
        }
        progress(100, "Done!");
    }

    static void WriteFile(FileStream dst, Iso.Rec rec, byte[] content)
    {
        long alloc = Align2(rec.Size, Iso.Sector);
        long pos;
        if (content.Length <= alloc) pos = (long)rec.Lba * Iso.Sector;
        else { pos = Align2(dst.Length, Iso.Sector); }
        dst.Position = pos; dst.Write(content, 0, content.Length);
        int pad = (int)(Align2(content.Length, Iso.Sector) - content.Length);
        if (pad > 0) dst.Write(new byte[pad], 0, pad);
        Iso.SetExtent(dst, rec, (uint)(pos / Iso.Sector), (uint)content.Length);
    }

    public static long Align2(long v, long a) { return (v + a - 1) / a * a; }
    static byte[] ReadExtent(Stream s, Iso.Rec r) { byte[] b = new byte[r.Size]; s.Position = (long)r.Lba * Iso.Sector; Iso.ReadFully(s, b, 0, b.Length); return b; }
    static byte[] Sha1(byte[] b) { using (SHA1 h = SHA1.Create()) return h.ComputeHash(b); }
    static bool Same(byte[] a, byte[] b) { if (a.Length != b.Length) return false; for (int i = 0; i < a.Length; i++) if (a[i] != b[i]) return false; return true; }
    static byte[] Slice(byte[] b, int o, int n) { byte[] r = new byte[n]; Array.Copy(b, o, r, 0, n); return r; }

    public static void Copy(Stream src, long from, Stream dst, long to, long n, Action<double> prog)
    {
        byte[] buf = new byte[1 << 20];
        src.Position = from; dst.Position = to;
        long done = 0;
        while (done < n)
        {
            int k = (int)Math.Min(buf.Length, n - done);
            Iso.ReadFully(src, buf, 0, k);
            dst.Write(buf, 0, k);
            done += k;
            if (prog != null && (done & ((16 << 20) - 1)) == 0) prog((double)done / n);
        }
    }
}

class Afs
{
    public long Base; public int Count; public uint First;
    public uint[] Off, Size; public uint NameOff, NameSize; public byte[] Names;

    public static Afs Read(Stream s, Iso.Rec rec)
    {
        Afs a = new Afs(); a.Base = (long)rec.Lba * Iso.Sector;
        byte[] h = new byte[8]; s.Position = a.Base; Iso.ReadFully(s, h, 0, 8);
        if (Encoding.ASCII.GetString(h, 0, 3) != "AFS") throw new Exception("Bad AFS archive.");
        a.Count = BitConverter.ToInt32(h, 4);
        byte[] toc = new byte[a.Count * 8 + 8]; Iso.ReadFully(s, toc, 0, toc.Length);
        a.Off = new uint[a.Count]; a.Size = new uint[a.Count];
        for (int i = 0; i < a.Count; i++) { a.Off[i] = BitConverter.ToUInt32(toc, i * 8); a.Size[i] = BitConverter.ToUInt32(toc, i * 8 + 4); }
        a.NameOff = BitConverter.ToUInt32(toc, a.Count * 8); a.NameSize = BitConverter.ToUInt32(toc, a.Count * 8 + 4);
        a.First = a.Off[0];
        if (a.NameOff != 0) { a.Names = new byte[a.NameSize]; s.Position = a.Base + a.NameOff; Iso.ReadFully(s, a.Names, 0, a.Names.Length); }
        return a;
    }

    public byte[] ReadEntry(Stream s, int i) { byte[] b = new byte[Size[i]]; s.Position = Base + Off[i]; Iso.ReadFully(s, b, 0, b.Length); return b; }

    // Same layout rules as the tested build: header+TOC, data from the original first offset, 0x800 alignment,
    // original name table copied at the end.
    public void Rebuild(Stream src, Stream dst, Dictionary<uint, byte[]> rep, Action<double> prog)
    {
        const int A = 0x800;
        long start = dst.Position;
        uint[] noff = new uint[Count], nsize = new uint[Count];
        long first = Math.Max(First, Patcher.Align2(8 + 8L * Count + 8, A));
        long pos = first;
        for (int i = 0; i < Count; i++)
        {
            byte[] r; uint sz = rep.TryGetValue((uint)i, out r) ? (uint)r.Length : Size[i];
            noff[i] = (uint)pos; nsize[i] = sz; pos = Patcher.Align2(pos + sz, A);
        }
        uint nameOff = Names != null ? (uint)pos : 0, nameSize = Names != null ? (uint)Names.Length : 0;
        byte[] head = new byte[first];
        Encoding.ASCII.GetBytes("AFS\0").CopyTo(head, 0);
        Iso.WriteLE(head, 4, (uint)Count);
        for (int i = 0; i < Count; i++) { Iso.WriteLE(head, 8 + i * 8, noff[i]); Iso.WriteLE(head, 12 + i * 8, nsize[i]); }
        Iso.WriteLE(head, 8 + Count * 8, nameOff); Iso.WriteLE(head, 12 + Count * 8, nameSize);
        dst.Write(head, 0, head.Length);
        byte[] zero = new byte[A];
        for (int i = 0; i < Count; i++)
        {
            byte[] r;
            if (rep.TryGetValue((uint)i, out r)) dst.Write(r, 0, r.Length);
            else { long here = dst.Position; Patcher.Copy(src, Base + Off[i], dst, here, Size[i], null); }
            long rel = dst.Position - start; int pad = (int)(Patcher.Align2(rel, A) - rel);
            if (pad > 0) dst.Write(zero, 0, pad);
            if (prog != null && i % 50 == 0) prog((double)i / Count);
        }
        if (Names != null)
        {
            dst.Write(Names, 0, Names.Length);
            long rel = dst.Position - start; int pad = (int)(Patcher.Align2(rel, A) - rel);
            if (pad > 0) dst.Write(zero, 0, pad);
        }
    }
}

class MainForm : Form
{
    TextBox inBox = new TextBox(), outBox = new TextBox();
    Button patchBtn = new Button();
    ProgressBar bar = new ProgressBar();
    Label status = new Label();

    public MainForm()
    {
        Text = "Ievan Polkka PV mod - Project DIVA (PSP)";
        ClientSize = new Size(560, 250); FormBorderStyle = FormBorderStyle.FixedDialog; MaximizeBox = false;
        Font = new Font("Segoe UI", 9f);
        Label intro = new Label();
        intro.Text = "Adds the full 3D Ievan Polkka PV (dance, camera, stage, leeks, lip sync) to your own copy of\n" +
                     "Hatsune Miku: Project DIVA (PSP, ULJM-05472) with the English patch v1.0.\n" +
                     "Your original ISO is not changed - a new modded ISO is written.";
        intro.SetBounds(12, 10, 540, 50);
        Label l1 = new Label(); l1.Text = "Your game ISO:"; l1.SetBounds(12, 70, 100, 20);
        inBox.SetBounds(115, 67, 340, 23);
        Button b1 = new Button(); b1.Text = "Browse..."; b1.SetBounds(462, 66, 85, 25);
        b1.Click += delegate
        {
            OpenFileDialog d = new OpenFileDialog(); d.Filter = "PSP ISO (*.iso)|*.iso|All files|*.*";
            if (d.ShowDialog() == DialogResult.OK)
            {
                inBox.Text = d.FileName;
                outBox.Text = Path.Combine(Path.GetDirectoryName(d.FileName),
                    Path.GetFileNameWithoutExtension(d.FileName) + " (Ievan Polkka mod).iso");
            }
        };
        Label l2 = new Label(); l2.Text = "Save modded ISO as:"; l2.SetBounds(12, 103, 110, 20);
        outBox.SetBounds(125, 100, 330, 23);
        Button b2 = new Button(); b2.Text = "Browse..."; b2.SetBounds(462, 99, 85, 25);
        b2.Click += delegate
        {
            SaveFileDialog d = new SaveFileDialog(); d.Filter = "PSP ISO (*.iso)|*.iso"; d.FileName = outBox.Text;
            if (d.ShowDialog() == DialogResult.OK) outBox.Text = d.FileName;
        };
        patchBtn.Text = "Install mod"; patchBtn.SetBounds(12, 140, 535, 32);
        patchBtn.Click += delegate { Start(); };
        bar.SetBounds(12, 182, 535, 20);
        status.SetBounds(12, 208, 535, 36); status.Text = "Choose your ISO, then click Install mod.";
        Controls.AddRange(new Control[] { intro, l1, inBox, b1, l2, outBox, b2, patchBtn, bar, status });
    }

    void Start()
    {
        string i = inBox.Text.Trim(), o = outBox.Text.Trim();
        if (!File.Exists(i)) { MessageBox.Show(this, "Pick your game ISO first."); return; }
        if (o.Length == 0 || string.Equals(Path.GetFullPath(i), Path.GetFullPath(o), StringComparison.OrdinalIgnoreCase))
        { MessageBox.Show(this, "Choose a different file name for the modded ISO."); return; }
        patchBtn.Enabled = false;
        Thread t = new Thread(delegate()
        {
            try
            {
                Patcher.Run(i, o, delegate(int pct, string msg) { BeginInvoke((MethodInvoker)delegate { bar.Value = Math.Min(100, pct); status.Text = msg; }); });
                BeginInvoke((MethodInvoker)delegate { status.Text = "Done! Modded ISO: " + o; MessageBox.Show(this, "Mod installed!\n\n" + o + "\n\nStart a new save: Ievan Polkka is unlocked in Free Play."); patchBtn.Enabled = true; });
            }
            catch (Exception e)
            {
                try { if (File.Exists(o)) File.Delete(o); } catch { }
                BeginInvoke((MethodInvoker)delegate { status.Text = "Failed."; MessageBox.Show(this, e.Message, "Mod install failed", MessageBoxButtons.OK, MessageBoxIcon.Error); patchBtn.Enabled = true; bar.Value = 0; });
            }
        });
        t.IsBackground = true; t.Start();
    }
}

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length >= 1)
        {
            string o = args.Length >= 2 ? args[1] : Path.Combine(Path.GetDirectoryName(Path.GetFullPath(args[0])),
                Path.GetFileNameWithoutExtension(args[0]) + " (Ievan Polkka mod).iso");
            try { Patcher.Run(args[0], o, delegate(int p, string m) { Console.WriteLine(p + "% " + m); }); return 0; }
            catch (Exception e)
            {
                try { if (File.Exists(o) && !string.Equals(Path.GetFullPath(o), Path.GetFullPath(args[0]), StringComparison.OrdinalIgnoreCase)) File.Delete(o); } catch { }
                Console.Error.WriteLine("ERROR: " + e.Message); return 1;
            }
        }
        Application.EnableVisualStyles();
        Application.Run(new MainForm());
        return 0;
    }
}

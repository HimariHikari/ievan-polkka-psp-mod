"""CRI AIX (multi-stream ADX) demux + ADX decoder."""
import struct, sys
import numpy as np

def demux(data):
    """Return {stream_id: adx_bytes} plus raw header bytes."""
    o = 0; streams = {}
    while o < len(data):
        tag = data[o:o + 4]; size = struct.unpack('>I', data[o + 4:o + 8])[0]
        if tag == b'AIXP':
            sid = data[o + 8]
            hdr = struct.unpack('>H', data[o + 10:o + 12])[0]  # header size within chunk (incl. 8-byte AIXP header?)
            streams.setdefault(sid, bytearray()).extend(data[o + 16:o + 8 + size])
        elif tag == b'AIXE':
            break
        o += 8 + size
    return {k: bytes(v) for k, v in streams.items()}

def adx_info(adx):
    assert adx[0] == 0x80, adx[:4].hex()
    off = struct.unpack('>H', adx[2:4])[0] + 4
    enc, bs, bits, ch = adx[4], adx[5], adx[6], adx[7]
    sr, ns = struct.unpack('>II', adx[8:16])
    cutoff = struct.unpack('>H', adx[16:18])[0]
    ver, flags = adx[18], adx[19]
    return dict(data_off=off, enc=enc, block=bs, bits=bits, channels=ch, rate=sr, samples=ns, cutoff=cutoff, version=ver, flags=flags)

def adx_decode(adx):
    info = adx_info(adx)
    assert info['enc'] == 3 and info['block'] == 18 and info['bits'] == 4, info
    assert info['flags'] == 0, 'encrypted ADX not supported: %r' % info
    ch, sr, ns = info['channels'], info['rate'], info['samples']
    a = np.sqrt(2.0) - np.cos(2.0 * np.pi * info['cutoff'] / sr)
    b = np.sqrt(2.0) - 1.0
    c = (a - np.sqrt((a + b) * (a - b))) / b
    c1 = int(np.floor(c * 8192)); c2 = int(np.floor(c * c * -4096))
    raw = np.frombuffer(adx, np.uint8, offset=info['data_off'])
    nblocks = (ns + 31) // 32
    raw = raw[:nblocks * 18 * ch].reshape(nblocks, ch, 18)
    scale = (raw[:, :, 0].astype(np.int32) << 8 | raw[:, :, 1]) + 1           # (nblocks, ch)
    nib = np.empty((nblocks, ch, 32), np.int32)
    nib[:, :, 0::2] = raw[:, :, 2:] >> 4
    nib[:, :, 1::2] = raw[:, :, 2:] & 15
    nib = np.where(nib >= 8, nib - 16, nib)
    delta = (nib * scale[:, :, None]).transpose(1, 0, 2).reshape(ch, -1)       # (ch, samples)
    out = np.zeros((ch, delta.shape[1]), np.int16)
    for k in range(ch):
        d = delta[k].tolist(); res = [0] * len(d); p1 = p2 = 0
        for i, dv in enumerate(d):
            s = dv + ((c1 * p1 + c2 * p2) >> 12)
            s = -32768 if s < -32768 else 32767 if s > 32767 else s
            res[i] = s; p2 = p1; p1 = s
        out[k] = res
    return out[:, :ns].T, sr

def write_wav(path, pcm, sr):
    pcm = np.ascontiguousarray(pcm, dtype='<i2')
    ch = pcm.shape[1]
    with open(path, 'wb') as f:
        f.write(b'RIFF' + struct.pack('<I', 36 + pcm.nbytes) + b'WAVEfmt ' +
                struct.pack('<IHHIIHH', 16, 1, ch, sr, sr * ch * 2, ch * 2, 16) + b'data' + struct.pack('<I', pcm.nbytes))
        f.write(pcm.tobytes())

if __name__ == '__main__':
    d = open(sys.argv[1], 'rb').read()
    s = demux(d)
    for k, v in sorted(s.items()):
        print(k, len(v), adx_info(v))
    if len(sys.argv) > 2:
        for k, v in sorted(s.items()):
            pcm, sr = adx_decode(v)
            write_wav(f'{sys.argv[2]}_{k}.wav', pcm, sr)
            print('wrote', f'{sys.argv[2]}_{k}.wav', pcm.shape, sr)

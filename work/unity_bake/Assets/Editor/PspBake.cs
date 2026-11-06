// Bakes a Unity Humanoid (muscle-space) AnimationClip onto the Project DIVA PSP Miku skeleton.
// Run headless:
//   Unity.exe -batchmode -nographics -projectPath <this project> -executeMethod PspBake.Run
//             -skel <psp_skeleton.json> -clip Assets/Clip/IevanPolkkaPD.anim -out <frames.bin> [-fps 30]
// Output (little-endian):
//   int32 frameCount, int32 boneCount, float32 fps
//   per frame: float32[3] root local position (PSP space), then per PSP bone float32[4] quaternion (PSP game convention)
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;

public static class PspBake
{
    [Serializable] class Bone { public string name; public int parent; public float[] t; }
    [Serializable] class BoneList { public Bone[] bones; }

    const string UpperChestDummy = "upperchest_dummy";

    static string Arg(string key, string def = null)
    {
        var a = Environment.GetCommandLineArgs();
        int i = Array.IndexOf(a, key);
        return (i >= 0 && i + 1 < a.Length) ? a[i + 1] : def;
    }

    public static void Run()
    {
        try { Bake(); EditorApplication.Exit(0); }
        catch (Exception e) { Debug.LogError("PSPBAKE FAILED: " + e); EditorApplication.Exit(1); }
    }

    static void Bake()
    {
        string skelPath = Arg("-skel"), clipPath = Arg("-clip"), outPath = Arg("-out");
        float fps = float.Parse(Arg("-fps", "30"), CultureInfo.InvariantCulture);
        var bl = JsonUtility.FromJson<BoneList>("{\"bones\":" + File.ReadAllText(skelPath) + "}");
        var bones = bl.bones;
        int n = bones.Length;

        // ---- rebuild the PSP skeleton in Unity space (mirror X: PSP is right-handed, Unity left-handed)
        var rootGo = new GameObject("psp_avatar");
        var tf = new Transform[n];
        tf[0] = rootGo.transform;                        // bone 0 = unnamed origin
        for (int i = 1; i < n; i++)
        {
            var b = bones[i];
            var t = new GameObject(b.name).transform;
            t.SetParent(tf[b.parent], false);
            t.localPosition = new Vector3(-b.t[0], b.t[1], b.t[2]);
            t.localRotation = Quaternion.identity;
            tf[i] = t;
        }
        Transform Find(string nm) => tf.First(x => x.name == nm);

        // ---- dummy UpperChest so the clip's UpperChest muscles are not lost; folded back into spine01 on export
        var spine01 = Find("spine01");
        var neck = Find("neck");
        var dummy = new GameObject(UpperChestDummy).transform;
        dummy.SetParent(spine01, false);
        dummy.localPosition = neck.localPosition * 0.25f;
        foreach (var c in spine01.Cast<Transform>().Where(c => c != dummy).ToList())
        {
            var wp = c.position;
            c.SetParent(dummy, true);
            c.position = wp;
            c.localRotation = Quaternion.identity;
        }

        var map = new Dictionary<string, string>
        {
            {"Hips","root"}, {"Spine","spine00"}, {"Chest","spine01"}, {"UpperChest",UpperChestDummy},
            {"Neck","neck"}, {"Head","head"},
            {"LeftShoulder","L_collar"}, {"LeftUpperArm","L_shouler"}, {"LeftLowerArm","L_ellbow"}, {"LeftHand","L_hand"},
            {"RightShoulder","R_collar"}, {"RightUpperArm","R_shouler"}, {"RightLowerArm","R_ellbow"}, {"RightHand","R_hand"},
            {"LeftUpperLeg","L_upleg"}, {"LeftLowerLeg","L_knee"}, {"LeftFoot","L_foot"}, {"LeftToes","L_toe"},
            {"RightUpperLeg","R_upleg"}, {"RightLowerLeg","R_knee"}, {"RightFoot","R_foot"}, {"RightToes","R_toe"},
        };
        var hd = new HumanDescription
        {
            human = map.Select(kv => new HumanBone { humanName = kv.Key, boneName = kv.Value, limit = new HumanLimit { useDefaultValues = true } }).ToArray(),
            skeleton = rootGo.GetComponentsInChildren<Transform>().Select(t => new SkeletonBone
            { name = t.name, position = t.localPosition, rotation = t.localRotation, scale = t.localScale }).ToArray(),
            upperArmTwist = 0.5f, lowerArmTwist = 0.5f, upperLegTwist = 0.5f, lowerLegTwist = 0.5f,
            armStretch = 0.05f, legStretch = 0.05f, feetSpacing = 0f, hasTranslationDoF = false,
        };
        var avatar = AvatarBuilder.BuildHumanAvatar(rootGo, hd);
        if (!avatar.isValid || !avatar.isHuman) throw new Exception("avatar invalid");
        Debug.Log($"PSPBAKE avatar ok, humanScale? bones={n}");

        // ---- clip curves -> muscle indices
        var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
        if (clip == null) throw new Exception("clip not found: " + clipPath);
        var muscleNames = HumanTrait.MuscleName;
        var muscleIndex = new Dictionary<string, int>();
        for (int i = 0; i < muscleNames.Length; i++) muscleIndex[muscleNames[i]] = i;
        string Norm(string p)
        {   // "LeftHand.Index.1 Stretched" -> "Left Index 1 Stretched"
            foreach (var side in new[] { "Left", "Right" })
                if (p.StartsWith(side + "Hand.")) return side + " " + p.Substring(side.Length + 5).Replace('.', ' ');
            return p;
        }
        var muscleCurves = new List<(int, AnimationCurve)>();
        var rootT = new AnimationCurve[3]; var rootQ = new AnimationCurve[4];
        foreach (var b in AnimationUtility.GetCurveBindings(clip))
        {
            if (b.type != typeof(Animator)) continue;
            var c = AnimationUtility.GetEditorCurve(clip, b);
            var p = b.propertyName;
            if (p.StartsWith("RootT.")) rootT["xyz".IndexOf(p[6])] = c;
            else if (p.StartsWith("RootQ.")) rootQ["xyzw".IndexOf(p[6])] = c;
            else if (muscleIndex.TryGetValue(Norm(p), out int mi)) muscleCurves.Add((mi, c));
            else Debug.Log("PSPBAKE skip curve " + p);
        }
        Debug.Log($"PSPBAKE muscles mapped={muscleCurves.Count} of {muscleNames.Length}; clip length={clip.length}");

        var handler = new HumanPoseHandler(avatar, rootGo.transform);
        var pose = new HumanPose();
        handler.GetHumanPose(ref pose);

        int frames = Mathf.FloorToInt(clip.length * fps + 0.5f) + 1;
        var lFoot = Find("L_foot"); var rFoot = Find("R_foot");
        float minFoot = float.MaxValue, maxFoot = float.MinValue;
        using (var w = new BinaryWriter(File.Create(outPath)))
        {
            w.Write(frames); w.Write(n); w.Write(fps);
            for (int f = 0; f < frames; f++)
            {
                float t = Mathf.Min(f / fps, clip.length);
                for (int i = 0; i < pose.muscles.Length; i++) pose.muscles[i] = 0f;
                foreach (var (mi, c) in muscleCurves) pose.muscles[mi] = c.Evaluate(t);
                pose.bodyPosition = new Vector3(rootT[0].Evaluate(t), rootT[1].Evaluate(t), rootT[2].Evaluate(t));
                pose.bodyRotation = new Quaternion(rootQ[0].Evaluate(t), rootQ[1].Evaluate(t), rootQ[2].Evaluate(t), rootQ[3].Evaluate(t)).normalized;
                handler.SetHumanPose(ref pose);

                var rootBone = tf[1];
                var rp = rootGo.transform.InverseTransformPoint(rootBone.position);   // root position in avatar space
                w.Write(-rp.x); w.Write(rp.y); w.Write(rp.z);
                for (int i = 0; i < n; i++)
                {
                    Quaternion q;
                    if (i == 0) q = Quaternion.identity;
                    else if (i == 1) q = Quaternion.Inverse(rootGo.transform.rotation) * rootBone.rotation;
                    else if (tf[i] == spine01) q = spine01.localRotation * dummy.localRotation;
                    else q = tf[i].localRotation;
                    // Unity (left-handed) -> PSP right-handed (mirror X): (x,-y,-z,w); PSP game stores the conjugate: (-x,y,z,w)
                    w.Write(-q.x); w.Write(q.y); w.Write(q.z); w.Write(q.w);
                }
                minFoot = Mathf.Min(minFoot, Mathf.Min(lFoot.position.y, rFoot.position.y));
                maxFoot = Mathf.Max(maxFoot, Mathf.Min(lFoot.position.y, rFoot.position.y));
            }
        }
        Debug.Log($"PSPBAKE wrote {frames} frames to {outPath}; lowest-foot ankle height min={minFoot:F3} max={maxFoot:F3} (rest ankle height {lFoot.parent.parent.parent.position.y:F3})");
    }
}

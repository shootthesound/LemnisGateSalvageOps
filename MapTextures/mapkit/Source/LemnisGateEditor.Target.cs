using UnrealBuildTool;

public class LemnisGateEditorTarget : TargetRules
{
	public LemnisGateEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.V2;
		ExtraModuleNames.AddRange(new string[] { "LemnisGate", "MapBuilder" });
	}
}

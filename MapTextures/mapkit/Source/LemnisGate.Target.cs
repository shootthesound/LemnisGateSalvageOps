using UnrealBuildTool;

public class LemnisGateTarget : TargetRules
{
	public LemnisGateTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.V2;
		ExtraModuleNames.Add("LemnisGate");
	}
}

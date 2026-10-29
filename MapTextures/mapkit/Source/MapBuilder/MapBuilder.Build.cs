using UnrealBuildTool;

// The map builder's core: a first-person editing app that knows nothing about any particular game. What a game
// contributes (its parts, gameplay objects and rules, and how a map is built) comes from a profile it reads.
public class MapBuilder : ModuleRules
{
	public MapBuilder(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "InputCore", "Json", "JsonUtilities", "Slate", "SlateCore", "RenderCore" });
	}
}

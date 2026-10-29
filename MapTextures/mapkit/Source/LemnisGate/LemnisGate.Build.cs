using UnrealBuildTool;

public class LemnisGate : ModuleRules
{
	public LemnisGate(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "UMG" });
		if (Target.bBuildEditor)
		{
			PrivateDependencyModuleNames.AddRange(new string[] { "UnrealEd", "Kismet", "BlueprintGraph", "AssetRegistry",
				"MeshDescription", "StaticMeshDescription", "Landscape" });
		}
	}
}

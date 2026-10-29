// Editor helpers the Map Kit's Python scripts call: Unreal 4.26 Python cannot add Blueprint components or
// volume brushes by itself.
#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MapKitLibrary.generated.h"

class AActor;
class AVolume;
class UMaterialInterface;
class UStaticMesh;
class UBlueprint;
class UWorld;

UCLASS()
class UMapKitLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()
public:
	// Create a Blueprint asset at PackagePath (e.g. /Game/Gameplay/Blueprints/JumpPad) deriving from Parent.
	// Its generated class is <Name>_C, like the game's. The default scene root is removed; components come from AddComponent.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static UBlueprint* CreateBlueprint(const FString& PackagePath, UClass* Parent);

	// Add a component to a Blueprint's construction script under Parent (one of its own, an inherited one or a native
	// one; None for a root). Returns the component template, named <Name>_GEN_VARIABLE like the game's.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static UActorComponent* AddComponent(UBlueprint* Blueprint, UClass* ComponentClass, FName Name, FName Parent);

	// Add an instance-editable variable. Type: float, int, bool, name, struct:<LinearColor|Color|Vector|Rotator> or
	// object:<class path>.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool AddVariable(UBlueprint* Blueprint, FName Name, FName Type);

	// Whether Class (or a parent) already has a property of this name, visible to Python or not.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool HasProperty(UClass* Class, FName Name);

	// Set any property from Unreal's text form, e.g. Mobility "Static" or LightColor "(B=49,G=48,R=182,A=255)".
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool SetPropertyText(UObject* Target, FName Name, const FString& Value);

	// Set an object-reference property by its Unreal name (Python cannot always reach Blueprint variables).
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool SetObjectProperty(UObject* Target, FName Name, UObject* Value);

	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool Compile(UBlueprint* Blueprint);

	// Give construction-script component templates the game's object names (component name -> template name;
	// "DefaultSceneRoot" for the default root). Older Blueprints use names like StaticMeshComponent_12.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static int32 RenameTemplates(UBlueprint* Blueprint, const TMap<FName, FName>& Names);

	// Levels without an editor viewport (the editor's own NewLevel needs one, so it crashes in a commandlet).
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static UWorld* CreateLevel(const FString& PackagePath);

	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static AActor* SpawnActor(UWorld* World, UClass* Class, FTransform Transform, FName Name);

	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool SaveLevel(UWorld* World);

	// Give an AtmosphericFogComponent precomputed sky tables (raw files taken from a game map). The editor only
	// computes them while rendering, which a commandlet never does.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool SetAtmosphereData(UActorComponent* Fog, const FString& TransmittanceFile, const FString& IrradianceFile,
		const FString& InscatterFile);

	// Create (or replace) a static mesh at PackagePath from a file mapkit/meshes.py wrote from the game's cooked mesh.
	// Material slots get the game's materials where the kit has them (placeholders otherwise).
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool ImportMesh(const FString& PackagePath, const FString& File);

	// Create a Landscape from a raw heightmap file (uint16 per vertex, row-major, 32768 = zero) covering vertices
	// Min..Max (inclusive), placed with Transform and drawn with Material. Returns the landscape.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static AActor* ImportLandscape(UWorld* World, const FString& HeightsFile, FIntPoint Min, FIntPoint Max,
		int32 NumSubsections, int32 SubsectionSizeQuads, FTransform Transform, UMaterialInterface* Material, FName Name);

	// An actor drawing Mesh many times (foliage): a hierarchical instanced mesh with the instances in File (4x4 float
	// matrices, row vectors, relative to the actor at Location).
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static AActor* SpawnInstancedMesh(UWorld* World, FName Name, UStaticMesh* Mesh, const TArray<UMaterialInterface*>& Materials,
		const FString& File, FVector Location, int32 CullStart, int32 CullEnd, FName CollisionProfile);

	// Drop an actor onto whatever is below it (traced from Up cm above down to Down cm below). False if nothing is.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static bool SnapToGround(AActor* Actor, float Up = 300.f, float Down = 5000.f);

	// Give a volume (KillZ, blocking, ...) a box brush of the given size in cm.
	UFUNCTION(BlueprintCallable, Category = "MapKit")
	static void MakeBoxBrush(AVolume* Volume, FVector Size);
};

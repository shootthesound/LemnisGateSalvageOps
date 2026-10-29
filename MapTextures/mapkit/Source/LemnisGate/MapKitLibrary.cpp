#include "MapKitLibrary.h"

#include "Components/HierarchicalInstancedStaticMeshComponent.h"
#include "Engine/StaticMesh.h"

#if WITH_EDITOR
#include "AssetRegistryModule.h"
#include "Atmosphere/AtmosphericFogComponent.h"
#include "Misc/FileHelper.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "PhysicsEngine/BodySetup.h"
#include "Serialization/MemoryReader.h"
#include "StaticMeshAttributes.h"
#include "Landscape.h"
#include "LandscapeInfo.h"
#include "BSPOps.h"
#include "Components/BrushComponent.h"
#include "Engine/Polys.h"
#include "Builders/CubeBuilder.h"
#include "EdGraphSchema_K2.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "GameFramework/Volume.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/KismetEditorUtilities.h"
#endif

UBlueprint* UMapKitLibrary::CreateBlueprint(const FString& PackagePath, UClass* Parent)
{
#if WITH_EDITOR
	if (!Parent)
	{
		return nullptr;
	}
	UPackage* Package = CreatePackage(*PackagePath);
	const FString Name = FPackageName::GetShortName(PackagePath);
	UBlueprint* Blueprint = FKismetEditorUtilities::CreateBlueprint(Parent, Package, *Name, BPTYPE_Normal,
		UBlueprint::StaticClass(), UBlueprintGeneratedClass::StaticClass());
	if (USimpleConstructionScript* SCS = Blueprint->SimpleConstructionScript)
	{
		if (USCS_Node* Default = SCS->GetDefaultSceneRootNode())
		{
			SCS->RemoveNode(Default, false);  // validating would put it straight back
		}
	}
	FAssetRegistryModule::AssetCreated(Blueprint);
	Package->MarkPackageDirty();
	return Blueprint;
#else
	return nullptr;
#endif
}

#if WITH_EDITOR
static USCS_Node* FindInheritedNode(UClass* Class, FName Name)
{
	for (UBlueprintGeneratedClass* C = Cast<UBlueprintGeneratedClass>(Class); C; C = Cast<UBlueprintGeneratedClass>(C->GetSuperClass()))
	{
		if (C->SimpleConstructionScript)
		{
			if (USCS_Node* Node = C->SimpleConstructionScript->FindSCSNode(Name))
			{
				return Node;
			}
		}
	}
	return nullptr;
}
#endif

UActorComponent* UMapKitLibrary::AddComponent(UBlueprint* Blueprint, UClass* ComponentClass, FName Name, FName Parent)
{
#if WITH_EDITOR
	if (!Blueprint || !ComponentClass || !Blueprint->SimpleConstructionScript)
	{
		return nullptr;
	}
	USimpleConstructionScript* SCS = Blueprint->SimpleConstructionScript;
	// The removed default root still owns the DefaultSceneRoot name, so a component of that name reuses it
	// (CreateNode would make DefaultSceneRoot1, which the game's Blueprint does not have).
	USCS_Node* Default = SCS->GetDefaultSceneRootNode();
	USCS_Node* Node = Default && Default->GetVariableName() == Name && !SCS->GetRootNodes().Contains(Default)
		? Default : SCS->CreateNode(ComponentClass, Name);
	if (Parent.IsNone())
	{
		SCS->AddNode(Node);
	}
	else if (USCS_Node* Own = SCS->FindSCSNode(Parent))
	{
		Own->AddChildNode(Node);
	}
	else
	{
		SCS->AddNode(Node);
		if (USCS_Node* Inherited = FindInheritedNode(Blueprint->ParentClass, Parent))
		{
			Node->SetParent(Inherited);
		}
		else if (AActor* CDO = Cast<AActor>(Blueprint->ParentClass->GetDefaultObject()))
		{
			TInlineComponentArray<USceneComponent*> Components;
			CDO->GetComponents(Components);
			for (USceneComponent* C : Components)
			{
				if (C->GetFName() == Parent)
				{
					Node->SetParent(C);
					break;
				}
			}
		}
	}
	return Node->ComponentTemplate;
#else
	return nullptr;
#endif
}

bool UMapKitLibrary::AddVariable(UBlueprint* Blueprint, FName Name, FName Type)
{
#if WITH_EDITOR
	FEdGraphPinType PinType;
	if (Type.ToString().StartsWith(TEXT("array:")))
	{
		PinType.ContainerType = EPinContainerType::Array;
		Type = FName(*Type.ToString().Mid(6));
	}
	if (Type == TEXT("float"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_Float;
	}
	else if (Type == TEXT("int"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_Int;
	}
	else if (Type == TEXT("bool"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_Boolean;
	}
	else if (Type == TEXT("name"))
	{
		PinType.PinCategory = UEdGraphSchema_K2::PC_Name;
	}
	else if (Type.ToString().StartsWith(TEXT("struct:")))
	{
		const FString Struct = Type.ToString().Mid(7);
		UScriptStruct* Found = Struct == TEXT("LinearColor") ? TBaseStructure<FLinearColor>::Get()
			: Struct == TEXT("Color") ? TBaseStructure<FColor>::Get()
			: Struct == TEXT("Vector") ? TBaseStructure<FVector>::Get()
			: Struct == TEXT("Rotator") ? TBaseStructure<FRotator>::Get() : nullptr;
		if (!Found)
		{
			return false;
		}
		PinType.PinCategory = UEdGraphSchema_K2::PC_Struct;
		PinType.PinSubCategoryObject = Found;
	}
	else if (Type.ToString().StartsWith(TEXT("object:")))
	{
		UClass* Class = LoadObject<UClass>(nullptr, *Type.ToString().Mid(7));
		if (!Class)
		{
			return false;
		}
		PinType.PinCategory = UEdGraphSchema_K2::PC_Object;
		PinType.PinSubCategoryObject = Class;
	}
	else
	{
		return false;
	}
	if (!FBlueprintEditorUtils::AddMemberVariable(Blueprint, Name, PinType))
	{
		return false;
	}
	FBlueprintEditorUtils::SetBlueprintOnlyEditableFlag(Blueprint, Name, false);
	return true;
#else
	return false;
#endif
}

bool UMapKitLibrary::HasProperty(UClass* Class, FName Name)
{
	return Class && FindFProperty<FProperty>(Class, Name) != nullptr;
}

bool UMapKitLibrary::SetPropertyText(UObject* Target, FName Name, const FString& Value)
{
	FProperty* Property = Target ? FindFProperty<FProperty>(Target->GetClass(), Name) : nullptr;
	return Property && Property->ImportText(*Value, Property->ContainerPtrToValuePtr<void>(Target), PPF_None, Target) != nullptr;
}

bool UMapKitLibrary::SetObjectProperty(UObject* Target, FName Name, UObject* Value)
{
	FObjectPropertyBase* Property = Target ? FindFProperty<FObjectPropertyBase>(Target->GetClass(), Name) : nullptr;
	if (!Property || (Value && !Value->IsA(Property->PropertyClass)))
	{
		return false;
	}
	Property->SetObjectPropertyValue_InContainer(Target, Value);
	return true;
}

bool UMapKitLibrary::Compile(UBlueprint* Blueprint)
{
#if WITH_EDITOR
	if (Blueprint->SimpleConstructionScript)
	{
		Blueprint->SimpleConstructionScript->ValidateSceneRootNodes();
	}
	FKismetEditorUtilities::CompileBlueprint(Blueprint);
	return Blueprint->Status != BS_Error;
#else
	return false;
#endif
}

int32 UMapKitLibrary::RenameTemplates(UBlueprint* Blueprint, const TMap<FName, FName>& Names)
{
	int32 Renamed = 0;
#if WITH_EDITOR
	USimpleConstructionScript* SCS = Blueprint ? Blueprint->SimpleConstructionScript : nullptr;
	if (!SCS)
	{
		return 0;
	}
	TArray<USCS_Node*> Nodes = SCS->GetAllNodes();
	if (USCS_Node* Default = SCS->GetDefaultSceneRootNode())
	{
		Nodes.AddUnique(Default);
	}
	for (USCS_Node* Node : Nodes)
	{
		const FName* Wanted = Names.Find(Node->GetVariableName());
		UActorComponent* Template = Node->ComponentTemplate;
		if (!Wanted || !Template || Template->GetFName() == *Wanted)
		{
			continue;
		}
		if (StaticFindObjectFast(nullptr, Template->GetOuter(), *Wanted))
		{
			continue;  // taken
		}
		if (Template->Rename(*Wanted->ToString(), nullptr, REN_DontCreateRedirectors | REN_ForceNoResetLoaders | REN_NonTransactional))
		{
			++Renamed;
		}
	}
	if (Renamed)
	{
		Blueprint->MarkPackageDirty();
	}
#endif
	return Renamed;
}

UWorld* UMapKitLibrary::CreateLevel(const FString& PackagePath)
{
#if WITH_EDITOR
	UPackage* Package = CreatePackage(*PackagePath);
	UWorld* World = UWorld::CreateWorld(EWorldType::Editor, false, FName(*FPackageName::GetShortName(PackagePath)), Package);
	World->SetFlags(RF_Public | RF_Standalone | RF_Transactional);
	Package->ThisContainsMap();
	FAssetRegistryModule::AssetCreated(World);
	Package->MarkPackageDirty();
	return World;
#else
	return nullptr;
#endif
}

AActor* UMapKitLibrary::SpawnActor(UWorld* World, UClass* Class, FTransform Transform, FName Name)
{
	if (!World || !Class)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.Name = Name.IsNone() ? NAME_None : MakeUniqueObjectName(World->PersistentLevel, Class, Name);
	AActor* Actor = World->SpawnActor(Class, &Transform, Params);
	if (!Actor)
	{
		return nullptr;
	}
	// SpawnActor stamps the override onto the actor; keep the class default so the level doesn't save it.
	Actor->SpawnCollisionHandlingMethod = Class->GetDefaultObject<AActor>()->SpawnCollisionHandlingMethod;
#if WITH_EDITOR
	if (!Name.IsNone())
	{
		Actor->SetActorLabel(Name.ToString());
	}
#endif
	return Actor;
}

bool UMapKitLibrary::SaveLevel(UWorld* World)
{
#if WITH_EDITOR
	UPackage* Package = World->GetOutermost();
	const FString File = FPackageName::LongPackageNameToFilename(Package->GetName(), FPackageName::GetMapPackageExtension());
	return UPackage::SavePackage(Package, World, RF_Standalone, *File, GError, nullptr, false, true, SAVE_NoError);
#else
	return false;
#endif
}

#if WITH_EDITOR
static bool LoadBulk(FByteBulkData& Bulk, const FString& File)
{
	TArray<uint8> Bytes;
	if (!FFileHelper::LoadFileToArray(Bytes, *File) || Bytes.Num() == 0)
	{
		return false;
	}
	Bulk.Lock(LOCK_READ_WRITE);
	FMemory::Memcpy(Bulk.Realloc(Bytes.Num()), Bytes.GetData(), Bytes.Num());
	Bulk.Unlock();
	return true;
}
#endif

bool UMapKitLibrary::SetAtmosphereData(UActorComponent* Fog, const FString& TransmittanceFile,
	const FString& IrradianceFile, const FString& InscatterFile)
{
#if WITH_EDITOR
PRAGMA_DISABLE_DEPRECATION_WARNINGS
	UAtmosphericFogComponent* Atmosphere = Cast<UAtmosphericFogComponent>(Fog);
	if (!Atmosphere || !LoadBulk(Atmosphere->TransmittanceData, TransmittanceFile)
		|| !LoadBulk(Atmosphere->IrradianceData, IrradianceFile) || !LoadBulk(Atmosphere->InscatterData, InscatterFile))
	{
		return false;
	}
	Atmosphere->PrecomputeCounter = UAtmosphericFogComponent::EValid;
	Atmosphere->MarkPackageDirty();
	return true;
PRAGMA_ENABLE_DEPRECATION_WARNINGS
#else
	return false;
#endif
}

#if WITH_EDITOR
static FString ReadText(FArchive& Ar)
{
	int32 Length = 0;
	Ar << Length;
	TArray<uint8> Utf8;
	Utf8.SetNumZeroed(Length + 1);
	Ar.Serialize(Utf8.GetData(), Length);
	return UTF8_TO_TCHAR((const ANSICHAR*)Utf8.GetData());
}
#endif

bool UMapKitLibrary::ImportMesh(const FString& PackagePath, const FString& File)
{
#if WITH_EDITOR
	TArray<uint8> Bytes;
	if (!FFileHelper::LoadFileToArray(Bytes, *File))
	{
		return false;
	}
	FMemoryReader Ar(Bytes);
	int32 NumVertices = 0;
	Ar << NumVertices;
	TArray<FVector> Positions, Normals;
	Positions.SetNumUninitialized(NumVertices);
	Normals.SetNumUninitialized(NumVertices);
	Ar.Serialize(Positions.GetData(), NumVertices * sizeof(FVector));
	Ar.Serialize(Normals.GetData(), NumVertices * sizeof(FVector));
	int32 NumUVChannels = 0;
	Ar << NumUVChannels;
	if (NumUVChannels < 1 || NumUVChannels > 8)
	{
		return false;
	}
	TArray<TArray<FVector2D>> UVs;
	UVs.SetNum(NumUVChannels);
	for (TArray<FVector2D>& Channel : UVs)
	{
		Channel.SetNumUninitialized(NumVertices);
		Ar.Serialize(Channel.GetData(), NumVertices * sizeof(FVector2D));
	}
	int32 LightMapIndex = 0, LightMapResolution = 4;
	Ar << LightMapIndex << LightMapResolution;
	int32 NumSlots = 0;
	Ar << NumSlots;
	TArray<FName> SlotNames;
	TArray<FString> MaterialPaths;
	for (int32 i = 0; i < NumSlots; ++i)
	{
		FString Slot = ReadText(Ar);
		// The build matches sections to slots by name, so names must be unique.
		if (Slot.IsEmpty() || SlotNames.Contains(FName(*Slot)))
		{
			Slot = FString::Printf(TEXT("%s_%d"), *Slot, i);
		}
		SlotNames.Add(FName(*Slot));
		MaterialPaths.Add(ReadText(Ar));
	}
	int32 NumSections = 0;
	Ar << NumSections;
	TArray<FIntVector> Sections;  // material slot, first index, triangles
	for (int32 i = 0; i < NumSections; ++i)
	{
		FIntVector S;
		Ar << S.X << S.Y << S.Z;
		Sections.Add(S);
	}
	int32 NumIndices = 0;
	Ar << NumIndices;
	TArray<uint32> Indices;
	Indices.SetNumUninitialized(NumIndices);
	Ar.Serialize(Indices.GetData(), NumIndices * sizeof(uint32));
	if (Ar.IsError() || NumVertices == 0)
	{
		return false;
	}

	FMeshDescription Description;
	FStaticMeshAttributes Attributes(Description);
	Attributes.Register();
	TVertexAttributesRef<FVector> VertexPositions = Attributes.GetVertexPositions();
	TVertexInstanceAttributesRef<FVector> InstanceNormals = Attributes.GetVertexInstanceNormals();
	TVertexInstanceAttributesRef<FVector2D> InstanceUVs = Attributes.GetVertexInstanceUVs();
	TPolygonGroupAttributesRef<FName> GroupSlots = Attributes.GetPolygonGroupMaterialSlotNames();
	InstanceUVs.SetNumIndices(NumUVChannels);
	TArray<FVertexInstanceID> Instances;
	for (int32 i = 0; i < NumVertices; ++i)
	{
		const FVertexID Vertex = Description.CreateVertex();
		VertexPositions[Vertex] = Positions[i];
		const FVertexInstanceID Instance = Description.CreateVertexInstance(Vertex);
		InstanceNormals[Instance] = Normals[i];
		for (int32 Channel = 0; Channel < NumUVChannels; ++Channel)
		{
			InstanceUVs.Set(Instance, Channel, UVs[Channel][i]);
		}
		Instances.Add(Instance);
	}
	for (const FIntVector& S : Sections)
	{
		if (!SlotNames.IsValidIndex(S.X))
		{
			continue;
		}
		const FPolygonGroupID Group = Description.CreatePolygonGroup();
		GroupSlots[Group] = SlotNames[S.X];
		for (int32 t = 0; t < S.Z; ++t)
		{
			const int32 First = S.Y + t * 3;
			if (First + 2 >= Indices.Num())
			{
				break;
			}
			const uint32 A = Indices[First], B = Indices[First + 1], C = Indices[First + 2];
			if (A == B || B == C || A == C || FMath::Max3(A, B, C) >= (uint32)NumVertices
				|| Positions[A] == Positions[B] || Positions[B] == Positions[C] || Positions[A] == Positions[C])
			{
				continue;  // degenerate
			}
			Description.CreatePolygon(Group, TArray<FVertexInstanceID>{ Instances[A], Instances[B], Instances[C] });
		}
	}

	UPackage* Package = CreatePackage(*PackagePath);
	Package->FullyLoad();
	const FString Name = FPackageName::GetShortName(PackagePath);
	UStaticMesh* Mesh = FindObject<UStaticMesh>(Package, *Name);
	if (!Mesh)
	{
		Mesh = NewObject<UStaticMesh>(Package, *Name, RF_Public | RF_Standalone);
		FAssetRegistryModule::AssetCreated(Mesh);
	}
	Mesh->PreEditChange(nullptr);
	Mesh->StaticMaterials.Empty();
	for (int32 i = 0; i < SlotNames.Num(); ++i)
	{
		UMaterialInterface* Material = nullptr;
		FString PackageName, ObjectName;
		if (MaterialPaths[i].Split(TEXT("."), &PackageName, &ObjectName) && FPackageName::DoesPackageExist(PackageName))
		{
			Material = LoadObject<UMaterialInterface>(nullptr, *MaterialPaths[i]);
		}
		Mesh->StaticMaterials.Add(FStaticMaterial(Material, SlotNames[i], SlotNames[i]));
	}
	Mesh->GetSourceModels().Empty();
	FStaticMeshSourceModel& Source = Mesh->AddSourceModel();
	Source.BuildSettings.bRecomputeNormals = false;
	Source.BuildSettings.bRecomputeTangents = true;
	Source.BuildSettings.bGenerateLightmapUVs = false;
	Source.BuildSettings.bRemoveDegenerates = true;
	// The game's lightmap UVs and resolution, so lighting baked in the kit fits the game's own meshes.
	Mesh->LightMapCoordinateIndex = FMath::Clamp(LightMapIndex, 0, NumUVChannels - 1);
	Mesh->LightMapResolution = LightMapResolution;
	Mesh->CreateMeshDescription(0, MoveTemp(Description));
	Mesh->CommitMeshDescription(0);
	Mesh->CreateBodySetup();
	Mesh->BodySetup->CollisionTraceFlag = CTF_UseComplexAsSimple;  // so the editor can snap things onto it
	Mesh->Build(true);
	Mesh->PostEditChange();
	Package->MarkPackageDirty();
	const FString Filename = FPackageName::LongPackageNameToFilename(PackagePath, FPackageName::GetAssetPackageExtension());
	return UPackage::SavePackage(Package, Mesh, RF_Public | RF_Standalone, *Filename, GError, nullptr, false, true, SAVE_NoError);
#else
	return false;
#endif
}

AActor* UMapKitLibrary::ImportLandscape(UWorld* World, const FString& HeightsFile, FIntPoint Min, FIntPoint Max,
	int32 NumSubsections, int32 SubsectionSizeQuads, FTransform Transform, UMaterialInterface* Material, FName Name)
{
#if WITH_EDITOR
	TArray<uint8> Bytes;
	const int32 Count = (Max.X - Min.X + 1) * (Max.Y - Min.Y + 1);
	if (!World || !FFileHelper::LoadFileToArray(Bytes, *HeightsFile) || Bytes.Num() != Count * 2)
	{
		return nullptr;
	}
	TArray<uint16> Heights;
	Heights.SetNumUninitialized(Count);
	FMemory::Memcpy(Heights.GetData(), Bytes.GetData(), Bytes.Num());
	TMap<FGuid, TArray<uint16>> HeightData;
	HeightData.Add(FGuid(), MoveTemp(Heights));
	TMap<FGuid, TArray<FLandscapeImportLayerInfo>> LayerData;
	LayerData.Add(FGuid(), TArray<FLandscapeImportLayerInfo>());

	FActorSpawnParameters Params;
	Params.Name = Name.IsNone() ? NAME_None : MakeUniqueObjectName(World->PersistentLevel, ALandscape::StaticClass(), Name);
	ALandscape* Landscape = World->SpawnActor<ALandscape>(Transform.GetLocation(), Transform.Rotator(), Params);
	if (!Landscape)
	{
		return nullptr;
	}
	Landscape->bCanHaveLayersContent = false;  // plain heightmap, like the game's
	Landscape->LandscapeMaterial = Material;
	Landscape->SetActorRelativeScale3D(Transform.GetScale3D());
	Landscape->Import(FGuid::NewGuid(), Min.X, Min.Y, Max.X, Max.Y, NumSubsections, SubsectionSizeQuads, HeightData,
		nullptr, LayerData, ELandscapeImportAlphamapType::Additive);
	if (ULandscapeInfo* Info = Landscape->GetLandscapeInfo())
	{
		Info->UpdateLayerInfoMap(Landscape);
	}
	if (!Name.IsNone())
	{
		Landscape->SetActorLabel(Name.ToString());
	}
	return Landscape;
#else
	return nullptr;
#endif
}

AActor* UMapKitLibrary::SpawnInstancedMesh(UWorld* World, FName Name, UStaticMesh* Mesh, const TArray<UMaterialInterface*>& Materials,
	const FString& File, FVector Location, int32 CullStart, int32 CullEnd, FName CollisionProfile)
{
	TArray<uint8> Bytes;
	if (!World || !Mesh || !FFileHelper::LoadFileToArray(Bytes, *File) || Bytes.Num() % sizeof(FMatrix) != 0)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.Name = Name.IsNone() ? NAME_None : MakeUniqueObjectName(World->PersistentLevel, AActor::StaticClass(), Name);
	AActor* Actor = World->SpawnActor<AActor>(AActor::StaticClass(), FTransform(Location), Params);
	if (!Actor)
	{
		return nullptr;
	}
	UHierarchicalInstancedStaticMeshComponent* Instances = NewObject<UHierarchicalInstancedStaticMeshComponent>(
		Actor, TEXT("Instances"), RF_Transactional);
	Instances->SetMobility(EComponentMobility::Static);
	Instances->SetStaticMesh(Mesh);
	for (int32 i = 0; i < Materials.Num(); ++i)
	{
		if (Materials[i])
		{
			Instances->SetMaterial(i, Materials[i]);
		}
	}
	Instances->InstanceStartCullDistance = CullStart;
	Instances->InstanceEndCullDistance = CullEnd;
	Instances->SetCollisionProfileName(CollisionProfile);
	Actor->SetRootComponent(Instances);
	Actor->AddInstanceComponent(Instances);
	Instances->SetWorldLocation(Location);
	Instances->RegisterComponent();
	const int32 Count = Bytes.Num() / sizeof(FMatrix);
	for (int32 i = 0; i < Count; ++i)
	{
		FMatrix M;
		FMemory::Memcpy(&M.M[0][0], Bytes.GetData() + i * sizeof(FMatrix), sizeof(FMatrix));
		Instances->AddInstance(FTransform(M));
	}
	Instances->BuildTreeIfOutdated(false, true);
#if WITH_EDITOR
	if (!Name.IsNone())
	{
		Actor->SetActorLabel(Name.ToString());
	}
	Actor->SetFolderPath(TEXT("Foliage"));
#endif
	return Actor;
}

bool UMapKitLibrary::SnapToGround(AActor* Actor, float Up, float Down)
{
	UWorld* World = Actor ? Actor->GetWorld() : nullptr;
	if (!World)
	{
		return false;
	}
	const FVector Location = Actor->GetActorLocation();
	FCollisionQueryParams Params(SCENE_QUERY_STAT(MapKitSnap), true, Actor);
	FHitResult Hit;
	if (!World->LineTraceSingleByChannel(Hit, Location + FVector(0, 0, Up), Location - FVector(0, 0, Down), ECC_WorldStatic, Params))
	{
		return false;
	}
	Actor->SetActorLocation(Hit.ImpactPoint);
	return true;
}

void UMapKitLibrary::MakeBoxBrush(AVolume* Volume, FVector Size)
{
#if WITH_EDITOR
	// As the editor's (unexported) CreateBrushForVolumeActor does when placing a volume.
	UCubeBuilder* Builder = NewObject<UCubeBuilder>();
	Builder->X = Size.X;
	Builder->Y = Size.Y;
	Builder->Z = Size.Z;
	Volume->PreEditChange(nullptr);
	const EObjectFlags Flags = Volume->GetFlags() & (RF_Transient | RF_Transactional);
	Volume->PolyFlags = 0;
	Volume->Brush = NewObject<UModel>(Volume, NAME_None, Flags);
	Volume->Brush->Initialize(nullptr, true);
	Volume->Brush->Polys = NewObject<UPolys>(Volume->Brush, NAME_None, Flags);
	Volume->GetBrushComponent()->Brush = Volume->Brush;
	Volume->BrushBuilder = DuplicateObject<UBrushBuilder>(Builder, Volume);
	Builder->Build(Volume->GetWorld(), Volume);
	FBSPOps::csgPrepMovingBrush(Volume);
	for (FPoly& Poly : Volume->Brush->Polys->Element)
	{
		Poly.Material = nullptr;
	}
	Volume->PostEditChange();
#endif
}

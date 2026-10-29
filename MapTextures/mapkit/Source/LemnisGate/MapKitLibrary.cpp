#include "MapKitLibrary.h"

#if WITH_EDITOR
#include "AssetRegistryModule.h"
#include "Atmosphere/AtmosphericFogComponent.h"
#include "Misc/FileHelper.h"
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

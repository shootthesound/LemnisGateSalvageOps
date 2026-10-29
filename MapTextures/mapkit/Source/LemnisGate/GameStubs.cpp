#include "GameStubs.h"

#include "Components/StaticMeshComponent.h"
#include "GameFramework/RotatingMovementComponent.h"
#include "Modules/ModuleManager.h"
#include "Particles/ParticleSystemComponent.h"

IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, LemnisGate, "LemnisGate");

void AMapKitActor::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
#if WITH_EDITORONLY_DATA
	TInlineComponentArray<UActorComponent*> Components;
	GetComponents(Components);
	for (const TPair<FName, FName>& Link : ComponentLinks)
	{
		// An array of components ("Chunk1,Chunk2,..."), e.g. a destroyable objective's ChunksArray.
		if (FArrayProperty* Array = FindFProperty<FArrayProperty>(GetClass(), Link.Key))
		{
			FObjectPropertyBase* Inner = CastField<FObjectPropertyBase>(Array->Inner);
			if (!Inner)
			{
				continue;
			}
			TArray<FString> Names;
			Link.Value.ToString().ParseIntoArray(Names, TEXT(","));
			FScriptArrayHelper Helper(Array, Array->ContainerPtrToValuePtr<void>(this));
			Helper.EmptyValues();
			for (const FString& Name : Names)
			{
				UActorComponent* const* Found = Components.FindByPredicate([&](UActorComponent* C) { return C->GetName() == Name; });
				const int32 Index = Helper.AddValue();
				Inner->SetObjectPropertyValue(Helper.GetRawPtr(Index), Found && (*Found)->IsA(Inner->PropertyClass) ? *Found : nullptr);
			}
			continue;
		}
		FObjectPropertyBase* Property = FindFProperty<FObjectPropertyBase>(GetClass(), Link.Key);
		UActorComponent* const* Found = Components.FindByPredicate([&](UActorComponent* C) { return C->GetFName() == Link.Value; });
		if (Property && Found && (*Found)->IsA(Property->PropertyClass))
		{
			Property->SetObjectPropertyValue_InContainer(this, *Found);
		}
	}
	for (const TMap<FString, FString>* Values : { &ConstructionValues, &InstanceConstructionValues })
	{
		for (const TPair<FString, FString>& Value : *Values)
		{
			FString ComponentName, PropertyName;
			if (!Value.Key.Split(TEXT("."), &ComponentName, &PropertyName))
			{
				continue;
			}
			UActorComponent* const* Found = Components.FindByPredicate([&](UActorComponent* C) { return C->GetName() == ComponentName; });
			if (!Found)
			{
				continue;
			}
			UActorComponent* Component = *Found;
			USceneComponent* Scene = Cast<USceneComponent>(Component);
			if (Scene && PropertyName == TEXT("Mobility"))
			{
				const int64 Mobility = StaticEnum<EComponentMobility::Type>()->GetValueByNameString(Value.Value);
				if (Mobility != INDEX_NONE)
				{
					Scene->SetMobility((EComponentMobility::Type)Mobility);
				}
			}
			else if (FProperty* Property = FindFProperty<FProperty>(Component->GetClass(), *PropertyName))
			{
				Property->ImportText(*Value.Value, Property->ContainerPtrToValuePtr<void>(Component), PPF_None, Component);
			}
		}
	}
	for (const TPair<FString, FString>& Event : ComponentEvents)
	{
		FString ComponentName, PropertyName;
		UObject* Target = this;
		if (Event.Key.Split(TEXT("."), &ComponentName, &PropertyName))
		{
			UActorComponent* const* Found = Components.FindByPredicate([&](UActorComponent* C) { return C->GetName() == ComponentName; });
			Target = Found ? *Found : nullptr;
		}
		else
		{
			PropertyName = Event.Key;
		}
		FMulticastDelegateProperty* Property = Target ? FindFProperty<FMulticastDelegateProperty>(Target->GetClass(), *PropertyName) : nullptr;
		if (!Property)
		{
			continue;
		}
		// Set the whole list: adding one binding at a time is refused, because the function only exists on the
		// game's Blueprint.
		void* Value = Property->ContainerPtrToValuePtr<void>(Target);
		const FMulticastScriptDelegate* Existing = Property->GetMulticastDelegate(Value);
		FMulticastScriptDelegate Bindings = Existing ? *Existing : FMulticastScriptDelegate();
		TArray<FString> Functions;
		Event.Value.ParseIntoArray(Functions, TEXT(","));
		for (const FString& Function : Functions)
		{
			FScriptDelegate Delegate;
			Delegate.BindUFunction(this, *Function);
			Bindings.AddUnique(Delegate);
		}
		Property->SetMulticastDelegate(Value, MoveTemp(Bindings));
	}
#endif
}

AConvergenceLightningTower::AConvergenceLightningTower()
{
	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	CreateDefaultSubobject<UParticleSystemComponent>(TEXT("LightningParticleSystem"))->SetupAttachment(Root);
	CreateDefaultSubobject<UStaticMeshComponent>(TEXT("targetRotatingMesh"))->SetupAttachment(Root);
	CreateDefaultSubobject<URotatingMovementComponent>(TEXT("RotatingComponent"));
}

AConvergenceCharacter::AConvergenceCharacter(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer.SetDefaultSubobjectClass<UConvergenceMovementComponent>(ACharacter::CharacterMovementComponentName))
{
	CreateDefaultSubobject<UCharacterStateMachineComponent>(TEXT("CharacterStateMachineComponent"));
	CreateDefaultSubobject<UPoseableMeshComponent>(TEXT("StatusEffectsMesh"))->SetupAttachment(GetCapsuleComponent());
}

AConvergenceGameMode::AConvergenceGameMode()
{
	CreateDefaultSubobject<UGameModeStateMachine>(TEXT("GameModeStateMachine"));
}

// Stand-ins for Lemnis Gate's native (C++) classes, under the same names as the game's /Script/LemnisGate module.
// They only need the class names, parent types, built-in components and per-instance properties that maps use:
// a map cooked against them references the classes by name, and the game loads its real ones.
#pragma once

#include "CoreMinimal.h"
#include "Components/ActorComponent.h"
#include "Components/CapsuleComponent.h"
#include "Components/PoseableMeshComponent.h"
#include "Components/SphereComponent.h"
#include "Components/WidgetComponent.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/GameMode.h"
#include "GameFramework/GameState.h"
#include "GameFramework/HUD.h"
#include "GameFramework/PlayerStart.h"
#include "GameFramework/Volume.h"
#include "GameFramework/WorldSettings.h"
#include "Engine/GameInstance.h"
#include "GameStubs.generated.h"

UENUM(BlueprintType)
enum class ETeamSide : uint8
{
	Attacker,
	Defender,
	Neutral,
};

// ---------------------------------------------------------------- components

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UScreenClampedWidgetComponent : public UWidgetComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UConvergenceWidgetComponent : public UWidgetComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UExtendedHitSphere : public USphereComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UExtendedHitCapsule : public UCapsuleComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UFlagAnimatorComponent : public UActorComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UIdleBreaksComponent : public UActorComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UPerlinNoiseAnimationComponent : public USceneComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UInteractionComponent : public USceneComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType, meta = (BlueprintSpawnableComponent))
class UCharacterStateMachineComponent : public UActorComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType)
class UConvergenceMovementComponent : public UCharacterMovementComponent { GENERATED_BODY() };

UCLASS(Blueprintable, BlueprintType)
class UGameModeStateMachine : public UObject { GENERATED_BODY() };

// ---------------------------------------------------------------- level actors

// Base of the gameplay actor stand-ins. The game's actors only run their construction scripts in the editor and keep
// the results in the saved level: variables pointing at their own components (the jump pad's Centre ->
// Jump_Pad_Centre) and component settings (movable gate arms, team light colours). The stand-ins have no such scripts
// and the editor rebuilds components whenever it re-runs construction, so both are re-applied here every time.
UCLASS(Blueprintable)
class AMapKitActor : public AActor
{
	GENERATED_BODY()
public:
#if WITH_EDITORONLY_DATA
	// Variable -> component name.
	UPROPERTY(EditDefaultsOnly, Category = "Map Kit")
	TMap<FName, FName> ComponentLinks;

	// Component values the game's construction scripts set, which the game reads from the saved level
	// ("Gate_Base.Mobility" -> "Movable"). Per Blueprint, then per placed actor (team colours and such).
	UPROPERTY(EditDefaultsOnly, Category = "Map Kit")
	TMap<FString, FString> ConstructionValues;

	UPROPERTY(EditAnywhere, Category = "Map Kit")
	TMap<FString, FString> InstanceConstructionValues;

	// Event bindings the level keeps ("CharacterTrigger.OnComponentBeginOverlap" -> the game Blueprint's
	// BndEvt__... function, comma-separated if several). The game only binds component events when it runs
	// construction, which it never does for level actors, so without these flags and jump pads ignore players.
	// The functions only exist on the game's Blueprints: don't trigger these events in the editor.
	UPROPERTY(EditDefaultsOnly, Category = "Map Kit")
	TMap<FString, FString> ComponentEvents;
#endif
	virtual void OnConstruction(const FTransform& Transform) override;
};

UCLASS()
class AConvergenceWorldSettings : public AWorldSettings { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceSpawnPoint : public APlayerStart
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lemnis Gate")
	ETeamSide TeamSide = ETeamSide::Attacker;
};

UCLASS(Blueprintable)
class AConvergenceGatePod : public AMapKitActor
{
	GENERATED_BODY()
public:
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Lemnis Gate")
	ETeamSide TeamSide = ETeamSide::Attacker;
};

UCLASS(Blueprintable)
class AObjective : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class ACapturableObjectiveBase : public AObjective { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceJumpPad : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceCollectible : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class AFixedUpdateActor : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class AVictoryPodiumBase : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceWeapon : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceShield : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceLandMine : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceAoE : public AMapKitActor { GENERATED_BODY() };

UCLASS(Blueprintable)
class ATimeLoopInhibitorVolume : public AVolume { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceLightningTower : public AMapKitActor
{
	GENERATED_BODY()
public:
	AConvergenceLightningTower();
};

UCLASS(Blueprintable)
class AConvergenceCharacter : public ACharacter
{
	GENERATED_BODY()
public:
	AConvergenceCharacter(const FObjectInitializer& ObjectInitializer);
};

// ---------------------------------------------------------------- game framework

UCLASS(Blueprintable)
class AConvergenceGameMode : public AGameMode
{
	GENERATED_BODY()
public:
	AConvergenceGameMode();
};

UCLASS(Blueprintable)
class AConstructGameMode : public AGameMode { GENERATED_BODY() };  // no state machine (TrainingGameMode has none)

UCLASS(Blueprintable)
class AConvergenceGameState : public AGameState { GENERATED_BODY() };

UCLASS(Blueprintable)
class AConvergenceHUD : public AHUD { GENERATED_BODY() };

UCLASS(Blueprintable)
class UConvergenceGameInstance : public UGameInstance { GENERATED_BODY() };

// The builder's controls: an Xbox-style controller, nothing else. Aim with the crosshair, grab things and place them.
//
//   Left stick: fly   Right stick: look   LT / RT: down / up   Left stick click: faster
//   A: select what's under the crosshair   Right stick click: add to / remove from the selection   B: clear
//   X: grab the selection (it follows your aim and sits on surfaces; X again places it, B puts it back)
//      while grabbing: LB / RB rotate by the rotation step, right stick click: turn / tilt / roll axis,
//      D-pad up / down raise / lower, D-pad left / right smaller / bigger
//   Y: duplicate the selection and grab the copy
//   D-pad left / right: undo / redo   D-pad up / down: fly speed
//   Hold LB: Edit menu   Hold RB: Settings menu   Hold Menu: File menu (save, build and play, quit)
//   Radial menus: hold the button, point the right stick at an option, release. Sub-menus (grid size, rotation step)
//   stay open: point and press A, or B to back out.
//
// Self-test (for checking the builder without anyone at the controller):
//   -MapBuilderCamera=X,Y,Z,Pitch,Yaw   start the camera here
//   -MapBuilderTest=<folder>            select what's under the crosshair, grab, rotate, place, duplicate, save
//                                       builder.png, builder.json and the edits there, then quit
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "MapBuilderController.generated.h"

class UMapBuilderEdits;

struct FMapBuilderRadialItem
{
	FString Label;
	TFunction<void()> Action;
};

UCLASS()
class MAPBUILDER_API AMapBuilderController : public APlayerController
{
	GENERATED_BODY()
public:
	AMapBuilderController();

	TArray<AActor*> GetSelectedActors() const;
	AActor* GetTarget() const { return Target.Get(); }
	bool IsGrabbing() const { return bGrabbing; }
	float GetSpeed() const;
	float GetGrid() const { return Grid; }
	float GetAngleSnap() const { return AngleSnap; }
	const TCHAR* GetGrabAxisName() const;
	const UMapBuilderEdits* GetEdits() const { return Edits; }
	const FString& GetStatus() const { return Status; }
	double GetStatusTime() const { return StatusTime; }
	FString GetLevelPath() const;
	FString GetEditsFile() const;

	// The radial menu being shown (empty if none) and the option the stick points at (-1: none).
	const FString& GetRadialTitle() const { return RadialTitle; }
	const TArray<FMapBuilderRadialItem>& GetRadialItems() const { return RadialItems; }
	int32 GetRadialChoice() const { return RadialChoice; }

	bool Save();

protected:
	virtual void BeginPlay() override;
	virtual void SetupInputComponent() override;
	virtual void PlayerTick(float DeltaTime) override;

private:
	// Buttons
	void PressA();
	void PressB();
	void PressX();
	void PressY();
	void PressRightStick();
	void PressDPadLeft();
	void PressDPadRight();
	void PressDPadUp();
	void PressDPadDown();
	void PressLB();
	void ReleaseLB();
	void PressRB();
	void ReleaseRB();
	void PressMenu();
	void ReleaseMenu();

	// Radial menus
	void OpenRadial(const FString& Title, TArray<FMapBuilderRadialItem> Items, bool bSticky = false);
	void CloseRadial(bool bChoose);
	void EditMenu();
	void SettingsMenu();
	void FileMenu();
	void GridMenu();
	void RotationStepMenu();

	// Actions
	void Select(bool bToggle);
	void ClearSelection();
	void Grab();
	void Place();
	void CancelGrab();
	void Duplicate();
	void Delete();
	void DropToFloor();
	void Undo();
	void Redo();
	void Frame();
	void ResetRotation();
	void ResetScale();
	void BuildAndPlay();
	void ChangeSpeed(float Factor);
	void ToggleHelpers();
	void SetStatus(const FString& Text);

	// Every frame
	void Fly(float DeltaTime);
	void Look(float DeltaTime);
	void UpdateTarget();
	void UpdateGrab();
	void Draw() const;

	float Stick(const FKey& Key) const;
	FVector Aim(FVector* OutOrigin = nullptr) const;
	AActor* Trace(const TArray<AActor*>& Ignore, FHitResult* OutHit = nullptr) const;
	bool CanSelect(const AActor* Actor) const;

	// Self-test
	void RunSelfTest();
	void SelfTestEdit();
	void SelfTestShot();
	void SelfTestReport();

	TArray<TWeakObjectPtr<AActor>> Selection;
	TWeakObjectPtr<AActor> Target;  // under the crosshair
	UPROPERTY()
	UMapBuilderEdits* Edits;

	float Grid = 50.f;       // cm, 0 = off
	float AngleSnap = 15.f;  // degrees, 0 = off
	bool bHelpersHidden = false;

	// Grabbing: the selection follows the crosshair, standing on what's under it.
	bool bGrabbing = false;
	TArray<FTransform> GrabStart;
	FVector GrabPivot;
	float GrabBase = 0.f;    // pivot height above the selection's lowest point
	float GrabDistance = 1000.f;
	FQuat GrabTurn = FQuat::Identity;
	int32 GrabAxis = 0;      // 0 turn (around up), 1 tilt (around the camera's right), 2 roll (around the view)
	float GrabLift = 0.f, GrabScale = 1.f;
	void Rotate(float Sign);

	FString RadialTitle;
	TArray<FMapBuilderRadialItem> RadialItems;
	int32 RadialChoice = -1;
	bool bRadialSticky = false;  // stays open after its button is released: A chooses, B backs out

	FString Status;
	double StatusTime = 0.0;

	TArray<FString> BuildCommand;  // from the game profile
	FString SelfTestFolder;
	FTimerHandle SelfTestTimer;
};

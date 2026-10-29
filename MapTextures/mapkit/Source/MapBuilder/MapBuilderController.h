// The builder's controls.
//   Hold right mouse: look around, and fly with WASD / Q E (Shift: faster, wheel: speed).
//   Left click: select (Ctrl+click: add). Drag a handle to move / rotate / scale along it; drag the object itself to
//   slide it over surfaces. W / E / R: move / rotate / scale handles. G: grid snap, H: angle snap.
//   Delete, Ctrl+D duplicate, Ctrl+Z / Ctrl+Y undo / redo, End: drop to floor, F: frame, Esc: clear, Ctrl+S: save.
//   Ctrl+B: save, then build and play through the game's profile (-MapBuilderProfile=<json>, its "build" command);
//   the builder closes, as the level it opened is about to change.
//
// Self-test (for checking the builder without anyone at the keyboard):
//   -MapBuilderCamera=X,Y,Z,Pitch,Yaw   start the camera here
//   -MapBuilderTest=<folder>            select what's in the middle of the screen, run a few edits, save builder.png,
//                                       builder.json (selection, camera) and the edits there, then quit
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/PlayerController.h"
#include "MapBuilderController.generated.h"

class UMapBuilderEdits;

UENUM()
enum class EMapBuilderTool : uint8 { Move, Rotate, Scale };

UCLASS()
class MAPBUILDER_API AMapBuilderController : public APlayerController
{
	GENERATED_BODY()
public:
	AMapBuilderController();

	const TArray<TWeakObjectPtr<AActor>>& GetSelection() const { return Selection; }
	TArray<AActor*> GetSelectedActors() const;
	bool IsLooking() const { return bLooking; }
	float GetSpeed() const;
	EMapBuilderTool GetTool() const { return Tool; }
	float GetGrid() const { return Grid; }
	bool IsAngleSnap() const { return bAngleSnap; }
	const UMapBuilderEdits* GetEdits() const { return Edits; }
	const FString& GetStatus() const { return Status; }
	FString GetLevelPath() const;
	FString GetEditsFile() const;

	AActor* SelectAt(FVector2D ScreenPosition, bool bAdd);
	void ClearSelection();
	bool Save();

protected:
	virtual void BeginPlay() override;
	virtual void SetupInputComponent() override;
	virtual void PlayerTick(float DeltaTime) override;

private:
	// Mouse
	void LeftDown();
	void LeftUp();
	void StartLooking();
	void StopLooking();
	void Drag();

	// Keys
	void MoveTool() { if (!bLooking) Tool = EMapBuilderTool::Move; }
	void RotateTool() { if (!bLooking) Tool = EMapBuilderTool::Rotate; }
	void ScaleTool() { if (!bLooking) Tool = EMapBuilderTool::Scale; }
	void CycleGrid();
	void ToggleAngleSnap();
	void DeleteSelection();
	void DuplicateSelection();
	void UndoEdit();
	void RedoEdit();
	void DropToFloor();
	void SaveKey();
	void BuildAndPlay();
	void FrameSelection();
	void SpeedUp();
	void SlowDown();
	bool Ctrl() const;

	void Fly(float DeltaTime);
	bool CanSelect(const AActor* Actor) const;

	// Handles: an axis per world direction at the selection's pivot, a fixed size on screen.
	FVector Pivot() const;
	float HandleLength() const;
	int32 HandleUnderMouse() const;  // 0..2 = X/Y/Z, 3 = centre (uniform scale), -1 = none
	void DrawHandles() const;
	void DrawSelection() const;
	void SetStatus(const FString& Text);

	void RunSelfTest();
	void SelfTestSelect();
	void SelfTestEdit();
	void SelfTestShot();
	void SelfTestReport();

	TArray<TWeakObjectPtr<AActor>> Selection;
	UPROPERTY()
	UMapBuilderEdits* Edits;

	bool bLooking = false;
	EMapBuilderTool Tool = EMapBuilderTool::Move;
	float Grid = 50.f;  // cm; 0 = off
	bool bAngleSnap = true;

	// Dragging
	int32 DragHandle = -1;  // -1: none; 0..3 a handle; 4 = sliding the object over surfaces
	FVector2D DragStartMouse;
	TArray<FTransform> DragStart;
	FVector DragPivot;

	FString Status;
	double StatusTime = 0.0;

	TArray<FString> BuildCommand;  // from the game profile
	FString SelfTestFolder;
	FTimerHandle SelfTestTimer;
};

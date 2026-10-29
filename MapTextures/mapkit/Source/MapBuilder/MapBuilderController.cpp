#include "MapBuilderController.h"

#include "DrawDebugHelpers.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "HAL/PlatformProcess.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "TimerManager.h"
#include "UnrealClient.h"

#include "MapBuilderEdits.h"
#include "MapBuilderPawn.h"

static const FColor SelectedColor(255, 190, 40);
static const FColor TargetColor(200, 200, 200);
static const float DeadZone = 0.2f;
static const float LookSpeed = 140.f;  // degrees per second at full stick

static TArray<FString> HelperClasses;  // from the game profile: objects the game hides in a match (shown here)

AMapBuilderController::AMapBuilderController()
{
	bShowMouseCursor = false;
}

void AMapBuilderController::BeginPlay()
{
	Super::BeginPlay();
	Edits = NewObject<UMapBuilderEdits>(this);
	SetInputMode(FInputModeGameOnly());
	ConsoleCommand(TEXT("r.MotionBlurQuality 0"));  // a building tool wants a sharp picture while moving

	FString Camera;
	if (FParse::Value(FCommandLine::Get(), TEXT("MapBuilderCamera="), Camera, false))
	{
		TArray<FString> Parts;
		Camera.ParseIntoArray(Parts, TEXT(","));
		if (Parts.Num() >= 5 && GetPawn())
		{
			GetPawn()->SetActorLocation(FVector(FCString::Atof(*Parts[0]), FCString::Atof(*Parts[1]), FCString::Atof(*Parts[2])));
			SetControlRotation(FRotator(FCString::Atof(*Parts[3]), FCString::Atof(*Parts[4]), 0.f));
		}
	}
	FString ProfileFile, ProfileText;
	if (FParse::Value(FCommandLine::Get(), TEXT("MapBuilderProfile="), ProfileFile, false)
		&& FFileHelper::LoadFileToString(ProfileText, *ProfileFile))
	{
		TSharedPtr<FJsonObject> Profile;
		if (FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(ProfileText), Profile) && Profile.IsValid())
		{
			Profile->TryGetStringArrayField(TEXT("build"), BuildCommand);
			Profile->TryGetStringArrayField(TEXT("helpers"), HelperClasses);
		}
	}
	if (FParse::Value(FCommandLine::Get(), TEXT("MapBuilderTest="), SelfTestFolder, false))
	{
		RunSelfTest();
	}
}

void AMapBuilderController::SetupInputComponent()
{
	Super::SetupInputComponent();
	UInputComponent* In = InputComponent;
	In->BindKey(EKeys::Gamepad_FaceButton_Bottom, IE_Pressed, this, &AMapBuilderController::PressA);
	In->BindKey(EKeys::Gamepad_FaceButton_Right, IE_Pressed, this, &AMapBuilderController::PressB);
	In->BindKey(EKeys::Gamepad_FaceButton_Left, IE_Pressed, this, &AMapBuilderController::PressX);
	In->BindKey(EKeys::Gamepad_FaceButton_Top, IE_Pressed, this, &AMapBuilderController::PressY);
	In->BindKey(EKeys::Gamepad_RightThumbstick, IE_Pressed, this, &AMapBuilderController::PressRightStick);
	In->BindKey(EKeys::Gamepad_DPad_Left, IE_Pressed, this, &AMapBuilderController::PressDPadLeft);
	In->BindKey(EKeys::Gamepad_DPad_Right, IE_Pressed, this, &AMapBuilderController::PressDPadRight);
	In->BindKey(EKeys::Gamepad_DPad_Up, IE_Pressed, this, &AMapBuilderController::PressDPadUp);
	In->BindKey(EKeys::Gamepad_DPad_Down, IE_Pressed, this, &AMapBuilderController::PressDPadDown);
	In->BindKey(EKeys::Gamepad_LeftShoulder, IE_Pressed, this, &AMapBuilderController::PressLB);
	In->BindKey(EKeys::Gamepad_LeftShoulder, IE_Released, this, &AMapBuilderController::ReleaseLB);
	In->BindKey(EKeys::Gamepad_RightShoulder, IE_Pressed, this, &AMapBuilderController::PressRB);
	In->BindKey(EKeys::Gamepad_RightShoulder, IE_Released, this, &AMapBuilderController::ReleaseRB);
	In->BindKey(EKeys::Gamepad_Special_Right, IE_Pressed, this, &AMapBuilderController::PressMenu);
	In->BindKey(EKeys::Gamepad_Special_Right, IE_Released, this, &AMapBuilderController::ReleaseMenu);
}

void AMapBuilderController::PlayerTick(float DeltaTime)
{
	Super::PlayerTick(DeltaTime);
	if (RadialItems.Num())
	{
		// The right stick picks an option; flying still works.
		const FVector2D S(Stick(EKeys::Gamepad_RightX), Stick(EKeys::Gamepad_RightY));
		RadialStick = S;
		if (S.Size() > 0.5f)
		{
			// Option 0 at the top, going clockwise.
			const float Angle = FMath::Fmod(FMath::RadiansToDegrees(FMath::Atan2(S.X, S.Y)) + 360.f, 360.f);
			const float Slice = 360.f / RadialItems.Num();
			RadialChoice = FMath::FloorToInt(FMath::Fmod(Angle + Slice * 0.5f, 360.f) / Slice) % RadialItems.Num();
		}
	}
	else
	{
		Look(DeltaTime);
	}
	Fly(DeltaTime);
	if (bGrabbing)
	{
		UpdateGrab();
	}
	else
	{
		UpdateTarget();
	}
	Draw();
}

float AMapBuilderController::Stick(const FKey& Key) const
{
	const float V = GetInputAnalogKeyState(Key);
	return FMath::Abs(V) < DeadZone ? 0.f : (V - FMath::Sign(V) * DeadZone) / (1.f - DeadZone);
}

void AMapBuilderController::Look(float DeltaTime)
{
	const float X = Stick(EKeys::Gamepad_RightX), Y = Stick(EKeys::Gamepad_RightY);
	// A gentle curve: precise near the centre, fast at the edge.
	FRotator R = GetControlRotation();
	R.Yaw += X * FMath::Abs(X) * LookSpeed * DeltaTime;
	R.Pitch = FMath::ClampAngle(R.Pitch + Y * FMath::Abs(Y) * LookSpeed * 0.8f * DeltaTime, -89.f, 89.f);
	SetControlRotation(R);
}

void AMapBuilderController::Fly(float DeltaTime)
{
	APawn* P = GetPawn();
	if (!P)
	{
		return;
	}
	const FRotationMatrix View(GetControlRotation());
	const float Boost = IsInputKeyDown(EKeys::Gamepad_LeftThumbstick) ? 3.f : 1.f;
	P->AddMovementInput(View.GetUnitAxis(EAxis::X), Stick(EKeys::Gamepad_LeftY) * Boost);
	P->AddMovementInput(View.GetUnitAxis(EAxis::Y), Stick(EKeys::Gamepad_LeftX) * Boost);
	auto Trigger = [this](const FKey& Key) { const float V = GetInputAnalogKeyState(Key); return V < 0.15f ? 0.f : V; };
	const float Vertical = Trigger(EKeys::Gamepad_RightTriggerAxis) - Trigger(EKeys::Gamepad_LeftTriggerAxis);
	P->AddMovementInput(FVector::UpVector, Vertical * Boost);
}

float AMapBuilderController::GetSpeed() const
{
	const AMapBuilderPawn* P = Cast<AMapBuilderPawn>(GetPawn());
	return P ? P->GetSpeed() : 0.f;
}

void AMapBuilderController::ChangeSpeed(float Factor)
{
	if (AMapBuilderPawn* P = Cast<AMapBuilderPawn>(GetPawn()))
	{
		P->ScaleSpeed(Factor);
		SetStatus(FString::Printf(TEXT("Speed %.0f"), P->GetSpeed()));
	}
}

void AMapBuilderController::SetStatus(const FString& Text)
{
	Status = Text;
	StatusTime = FPlatformTime::Seconds();
}

FString AMapBuilderController::GetLevelPath() const
{
	return GetWorld()->GetOutermost()->GetName();
}

FString AMapBuilderController::GetEditsFile() const
{
	return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("MapBuilder"), FPaths::GetBaseFilename(GetLevelPath()) + TEXT(".edits.json"));
}

// ---------------------------------------------------------------- aiming and selection

FVector AMapBuilderController::Aim(FVector* OutOrigin) const
{
	FVector Loc;
	FRotator Rot;
	GetPlayerViewPoint(Loc, Rot);
	if (OutOrigin)
	{
		*OutOrigin = Loc;
	}
	return Rot.Vector();
}

AActor* AMapBuilderController::Trace(const TArray<AActor*>& Ignore, FHitResult* OutHit) const
{
	FVector Origin;
	const FVector Dir = Aim(&Origin);
	FCollisionQueryParams Params(SCENE_QUERY_STAT(MapBuilderAim), true, GetPawn());
	Params.AddIgnoredActors(Ignore);
	FHitResult Hit;
	if (!GetWorld()->LineTraceSingleByChannel(Hit, Origin, Origin + Dir * 200000.f, ECC_Visibility, Params))
	{
		return nullptr;
	}
	if (OutHit)
	{
		*OutHit = Hit;
	}
	return Hit.GetActor();
}

bool AMapBuilderController::CanSelect(const AActor* Actor) const
{
	if (!Actor || Actor == GetPawn() || Actor->IsA<AWorldSettings>() || UMapBuilderEdits::IsDeleted(Actor))
	{
		return false;
	}
	// The ground is edited with terrain tools, not selected as an object.
	return !Actor->GetClass()->GetName().Contains(TEXT("Landscape"));
}

void AMapBuilderController::UpdateTarget()
{
	AActor* Hit = Trace({});
	Target = CanSelect(Hit) ? Hit : nullptr;
}

TArray<AActor*> AMapBuilderController::GetSelectedActors() const
{
	TArray<AActor*> Out;
	for (const TWeakObjectPtr<AActor>& A : Selection)
	{
		if (A.IsValid() && !UMapBuilderEdits::IsDeleted(A.Get()))
		{
			Out.Add(A.Get());
		}
	}
	return Out;
}

void AMapBuilderController::Select(bool bToggle)
{
	AActor* T = Target.Get();
	if (!bToggle)
	{
		Selection.Reset();
	}
	if (T)
	{
		if (bToggle && Selection.Contains(T))
		{
			Selection.Remove(T);
		}
		else
		{
			Selection.AddUnique(T);
		}
	}
}

void AMapBuilderController::ClearSelection()
{
	Selection.Reset();
}

// ---------------------------------------------------------------- buttons

void AMapBuilderController::PressA()
{
	if (RadialItems.Num())
	{
		if (bRadialSticky)
		{
			CloseRadial(true);
		}
		return;
	}
	if (bGrabbing)
	{
		Place();
	}
	else
	{
		Select(false);
	}
}

void AMapBuilderController::PressB()
{
	if (RadialItems.Num())
	{
		CloseRadial(false);
	}
	else if (bGrabbing)
	{
		CancelGrab();
	}
	else
	{
		ClearSelection();
	}
}

void AMapBuilderController::PressX()
{
	if (RadialItems.Num())
	{
		return;
	}
	if (bGrabbing)
	{
		Place();
	}
	else
	{
		if (!GetSelectedActors().Num())
		{
			Select(false);  // grab what's under the crosshair
		}
		Grab();
	}
}

void AMapBuilderController::PressY()
{
	if (!RadialItems.Num() && !bGrabbing)
	{
		Duplicate();
	}
}

void AMapBuilderController::PressRightStick()
{
	if (bGrabbing)
	{
		GrabAxis = (GrabAxis + 1) % 3;
		SetStatus(FString::Printf(TEXT("Rotating: %s"), GetGrabAxisName()));
	}
	else if (!RadialItems.Num())
	{
		Select(true);
	}
}

const TCHAR* AMapBuilderController::GetGrabAxisName() const
{
	static const TCHAR* Names[] = { TEXT("turn"), TEXT("tilt"), TEXT("roll") };
	return Names[GrabAxis];
}

void AMapBuilderController::Rotate(float Sign)
{
	// World up for turning; the camera's right and forward (flattened) for tilting and rolling, so it rotates the way
	// you're looking at it.
	const FRotator View(0.f, GetControlRotation().Yaw, 0.f);
	const FVector Axis = GrabAxis == 0 ? FVector::UpVector : GrabAxis == 1 ? FRotationMatrix(View).GetUnitAxis(EAxis::Y)
	                                                                       : FRotationMatrix(View).GetUnitAxis(EAxis::X);
	const float Step = AngleSnap > 0.f ? AngleSnap : 1.f;
	GrabTurn = FQuat(Axis, FMath::DegreesToRadians(Sign * Step)) * GrabTurn;
}

void AMapBuilderController::PressDPadLeft()
{
	if (bGrabbing)
	{
		GrabScale = FMath::Max(0.05f, GrabScale / 1.1f);
	}
	else if (!RadialItems.Num())
	{
		Undo();
	}
}

void AMapBuilderController::PressDPadRight()
{
	if (bGrabbing)
	{
		GrabScale *= 1.1f;
	}
	else if (!RadialItems.Num())
	{
		Redo();
	}
}

void AMapBuilderController::PressDPadUp()
{
	if (bGrabbing)
	{
		GrabLift += Grid > 0.f ? Grid : 25.f;
	}
	else if (!RadialItems.Num())
	{
		ChangeSpeed(1.5f);
	}
}

void AMapBuilderController::PressDPadDown()
{
	if (bGrabbing)
	{
		GrabLift -= Grid > 0.f ? Grid : 25.f;
	}
	else if (!RadialItems.Num())
	{
		ChangeSpeed(1.f / 1.5f);
	}
}

void AMapBuilderController::PressLB()
{
	if (bGrabbing)
	{
		Rotate(-1.f);
	}
	else if (!RadialItems.Num())
	{
		EditMenu();
	}
}

void AMapBuilderController::ReleaseLB()
{
	if (RadialTitle == TEXT("Edit"))
	{
		CloseRadial(true);
	}
}

void AMapBuilderController::PressRB()
{
	if (bGrabbing)
	{
		Rotate(1.f);
	}
	else if (!RadialItems.Num())
	{
		SettingsMenu();
	}
}

void AMapBuilderController::ReleaseRB()
{
	if (RadialTitle == TEXT("Settings"))
	{
		CloseRadial(true);
	}
}

void AMapBuilderController::PressMenu()
{
	if (!RadialItems.Num() && !bGrabbing)
	{
		FileMenu();
	}
}

void AMapBuilderController::ReleaseMenu()
{
	if (RadialTitle == TEXT("File"))
	{
		CloseRadial(true);
	}
}

// ---------------------------------------------------------------- radial menus

void AMapBuilderController::OpenRadial(const FString& Title, TArray<FMapBuilderRadialItem> Items, bool bSticky)
{
	RadialTitle = Title;
	RadialItems = MoveTemp(Items);
	RadialChoice = -1;
	bRadialSticky = bSticky;
}

void AMapBuilderController::CloseRadial(bool bChoose)
{
	TFunction<void()> Action;
	if (bChoose && RadialItems.IsValidIndex(RadialChoice))
	{
		Action = RadialItems[RadialChoice].Action;
	}
	RadialTitle.Reset();
	RadialItems.Reset();
	RadialChoice = -1;
	bRadialSticky = false;
	if (Action)
	{
		Action();
	}
}

void AMapBuilderController::EditMenu()
{
	OpenRadial(TEXT("Edit"), {
		{ TEXT("Duplicate"), [this] { Duplicate(); } },
		{ TEXT("Drop to floor"), [this] { DropToFloor(); } },
		{ TEXT("Redo"), [this] { Redo(); } },
		{ TEXT("Reset scale"), [this] { ResetScale(); } },
		{ TEXT("Delete"), [this] { Delete(); } },
		{ TEXT("Reset rotation"), [this] { ResetRotation(); } },
		{ TEXT("Undo"), [this] { Undo(); } },
		{ TEXT("Frame selection"), [this] { Frame(); } },
	});
}

void AMapBuilderController::SettingsMenu()
{
	OpenRadial(TEXT("Settings"), {
		{ TEXT("Grid size..."), [this] { GridMenu(); } },
		{ TEXT("Rotation step..."), [this] { RotationStepMenu(); } },
		{ TEXT("Faster flying"), [this] { ChangeSpeed(1.5f); } },
		{ bHelpersHidden ? TEXT("Show helpers") : TEXT("Hide helpers"), [this] { ToggleHelpers(); } },
		{ TEXT("Slower flying"), [this] { ChangeSpeed(1.f / 1.5f); } },
	});
}

void AMapBuilderController::GridMenu()
{
	TArray<FMapBuilderRadialItem> Items;
	for (float G : { 0.f, 1.f, 5.f, 10.f, 25.f, 50.f, 100.f, 250.f })
	{
		Items.Add({ G > 0.f ? FString::Printf(TEXT("%.0f cm%s"), G, G == Grid ? TEXT("  *") : TEXT(""))
		                    : FString(Grid == 0.f ? TEXT("Off  *") : TEXT("Off")),
		            [this, G] { Grid = G; SetStatus(G > 0.f ? FString::Printf(TEXT("Grid %.0f cm"), G) : TEXT("Grid off")); } });
	}
	OpenRadial(TEXT("Grid size"), MoveTemp(Items), true);
}

void AMapBuilderController::RotationStepMenu()
{
	TArray<FMapBuilderRadialItem> Items;
	for (float A : { 0.f, 1.f, 5.f, 15.f, 45.f, 90.f })
	{
		Items.Add({ A > 0.f ? FString::Printf(TEXT("%.0f degrees%s"), A, A == AngleSnap ? TEXT("  *") : TEXT(""))
		                    : FString(AngleSnap == 0.f ? TEXT("Free (1 degree)  *") : TEXT("Free (1 degree)")),
		            [this, A] { AngleSnap = A; SetStatus(A > 0.f ? FString::Printf(TEXT("Rotation step %.0f degrees"), A) : TEXT("Rotation step 1 degree")); } });
	}
	OpenRadial(TEXT("Rotation step"), MoveTemp(Items), true);
}

void AMapBuilderController::FileMenu()
{
	OpenRadial(TEXT("File"), {
		{ TEXT("Save"), [this] { Save(); } },
		{ TEXT("Build and play"), [this] { BuildAndPlay(); } },
		{ TEXT("Quit (unsaved edits are lost)"), [this] { ConsoleCommand(TEXT("quit")); } },
	});
}

// ---------------------------------------------------------------- grabbing

void AMapBuilderController::Grab()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	if (!Actors.Num())
	{
		SetStatus(TEXT("Nothing to grab: aim at something and press X"));
		return;
	}
	Edits->BeginTransform(Actors);  // also makes them movable
	GrabStart.Reset();
	FBox Bounds(ForceInit);
	FVector Sum = FVector::ZeroVector;
	for (AActor* A : Actors)
	{
		GrabStart.Add(A->GetActorTransform());
		Bounds += A->GetComponentsBoundingBox(true);
		Sum += A->GetActorLocation();
	}
	GrabPivot = Sum / Actors.Num();
	GrabBase = GrabPivot.Z - Bounds.Min.Z;
	FVector Origin;
	Aim(&Origin);
	GrabDistance = FVector::Dist(Origin, GrabPivot);
	GrabTurn = FQuat::Identity;
	GrabLift = 0.f;
	GrabScale = 1.f;
	bGrabbing = true;
}

void AMapBuilderController::UpdateGrab()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	if (Actors.Num() != GrabStart.Num())
	{
		CancelGrab();
		return;
	}
	// Stand on what the crosshair points at, or hang in the air at the distance it was grabbed from.
	FHitResult Hit;
	FVector Pivot;
	if (Trace(Actors, &Hit) && FVector::Dist(Hit.ImpactPoint, Hit.TraceStart) < GrabDistance * 4.f + 2000.f)
	{
		Pivot = Hit.ImpactPoint + FVector(0, 0, GrabBase * GrabScale);
	}
	else
	{
		FVector Origin;
		const FVector Dir = Aim(&Origin);
		Pivot = Origin + Dir * GrabDistance;
	}
	if (Grid > 0.f)
	{
		Pivot.X = FMath::GridSnap(Pivot.X, Grid);
		Pivot.Y = FMath::GridSnap(Pivot.Y, Grid);
	}
	Pivot.Z += GrabLift;
	const FQuat& Turn = GrabTurn;
	for (int32 i = 0; i < Actors.Num(); ++i)
	{
		const FTransform& S = GrabStart[i];
		FTransform T;
		T.SetLocation(Pivot + Turn.RotateVector((S.GetLocation() - GrabPivot) * GrabScale));
		T.SetRotation(Turn * S.GetRotation());
		T.SetScale3D(S.GetScale3D() * GrabScale);
		Actors[i]->SetActorTransform(T);
	}
}

void AMapBuilderController::Place()
{
	bGrabbing = false;
	Edits->EndTransform();
	SetStatus(TEXT("Placed"));
}

void AMapBuilderController::CancelGrab()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	for (int32 i = 0; i < Actors.Num() && i < GrabStart.Num(); ++i)
	{
		Actors[i]->SetActorTransform(GrabStart[i]);
	}
	bGrabbing = false;
	Edits->EndTransform();  // unchanged, so nothing is recorded
	SetStatus(TEXT("Put back"));
}

// ---------------------------------------------------------------- actions

void AMapBuilderController::Duplicate()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	if (!Actors.Num())
	{
		SetStatus(TEXT("Select something to duplicate"));
		return;
	}
	const TArray<AActor*> Copies = Edits->Duplicate(Actors, FVector::ZeroVector);
	Selection.Reset();
	for (AActor* A : Copies)
	{
		Selection.Add(A);
	}
	Grab();  // straight into your hands, to put down where you want it
}

void AMapBuilderController::Delete()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	if (Actors.Num())
	{
		Edits->Delete(Actors);
		Selection.Reset();
		SetStatus(FString::Printf(TEXT("Deleted %d"), Actors.Num()));
	}
}

void AMapBuilderController::DropToFloor()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	if (!Actors.Num())
	{
		return;
	}
	Edits->BeginTransform(Actors);
	for (AActor* A : Actors)
	{
		const FBox Box = A->GetComponentsBoundingBox(true);
		FCollisionQueryParams Params(SCENE_QUERY_STAT(MapBuilderDrop), true, GetPawn());
		Params.AddIgnoredActors(Actors);
		FHitResult Hit;
		const FVector Start(Box.GetCenter().X, Box.GetCenter().Y, Box.Min.Z + 1.f);
		if (GetWorld()->LineTraceSingleByChannel(Hit, Start, Start - FVector(0, 0, 100000.f), ECC_Visibility, Params))
		{
			A->AddActorWorldOffset(FVector(0, 0, Hit.ImpactPoint.Z - Box.Min.Z));
		}
	}
	Edits->EndTransform();
	SetStatus(TEXT("Dropped to floor"));
}

void AMapBuilderController::ResetRotation()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	Edits->BeginTransform(Actors);
	for (AActor* A : Actors)
	{
		A->SetActorRotation(FRotator::ZeroRotator);
	}
	Edits->EndTransform();
}

void AMapBuilderController::ResetScale()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	Edits->BeginTransform(Actors);
	for (AActor* A : Actors)
	{
		A->SetActorScale3D(FVector::OneVector);
	}
	Edits->EndTransform();
}

void AMapBuilderController::Undo()
{
	SetStatus(Edits->Undo() ? TEXT("Undo") : TEXT("Nothing to undo"));
}

void AMapBuilderController::Redo()
{
	SetStatus(Edits->Redo() ? TEXT("Redo") : TEXT("Nothing to redo"));
}

void AMapBuilderController::Frame()
{
	FBox Bounds(ForceInit);
	for (AActor* A : GetSelectedActors())
	{
		Bounds += A->GetComponentsBoundingBox(true);
	}
	if (Bounds.IsValid && GetPawn())
	{
		const float Distance = FMath::Max(300.f, Bounds.GetExtent().Size() * 2.5f);
		GetPawn()->SetActorLocation(Bounds.GetCenter() - GetControlRotation().Vector() * Distance);
	}
}

void AMapBuilderController::ToggleHelpers()
{
	bHelpersHidden = !bHelpersHidden;
	int32 Count = 0;
	for (TActorIterator<AActor> It(GetWorld()); It; ++It)
	{
		const FString Class = It->GetClass()->GetName();
		if (HelperClasses.ContainsByPredicate([&](const FString& H) { return Class.Contains(H); }) && !UMapBuilderEdits::IsDeleted(*It))
		{
			It->SetActorHiddenInGame(bHelpersHidden);
			It->SetActorEnableCollision(!bHelpersHidden);
			++Count;
		}
	}
	SetStatus(FString::Printf(TEXT("%s %d helpers"), bHelpersHidden ? TEXT("Hid") : TEXT("Showing"), Count));
}

bool AMapBuilderController::Save()
{
	const bool bOk = Edits->Save(GetEditsFile(), GetLevelPath());
	SetStatus(bOk ? TEXT("Saved") : TEXT("Could not save"));
	return bOk;
}

void AMapBuilderController::BuildAndPlay()
{
	if (BuildCommand.Num() == 0)
	{
		SetStatus(TEXT("This game's profile has no build command"));
		return;
	}
	if (!Save())
	{
		return;
	}
	FString Params;
	for (int32 i = 1; i < BuildCommand.Num(); ++i)
	{
		Params += TEXT("\"") + BuildCommand[i] + TEXT("\" ");
	}
	// In its own console window, so the build's progress is visible after the builder closes.
	FProcHandle Proc = FPlatformProcess::CreateProc(*BuildCommand[0], *Params, true, false, false, nullptr, 0, nullptr, nullptr);
	if (!Proc.IsValid())
	{
		SetStatus(TEXT("Could not start the build"));
		return;
	}
	ConsoleCommand(TEXT("quit"));  // the level it opened is about to change
}

// ---------------------------------------------------------------- drawing

void AMapBuilderController::Draw() const
{
	for (AActor* A : GetSelectedActors())
	{
		const FBox Box = A->GetComponentsBoundingBox(true);
		DrawDebugBox(GetWorld(), Box.GetCenter(), Box.GetExtent(), SelectedColor, false, -1.f, SDPG_Foreground, bGrabbing ? 3.f : 1.5f);
	}
	if (AActor* T = Target.Get())
	{
		if (!bGrabbing && !GetSelectedActors().Contains(T))
		{
			const FBox Box = T->GetComponentsBoundingBox(true);
			DrawDebugBox(GetWorld(), Box.GetCenter(), Box.GetExtent(), TargetColor, false, -1.f, SDPG_Foreground, 0.75f);
		}
	}
}

// ---------------------------------------------------------------- self-test

void AMapBuilderController::RunSelfTest()
{
	// Give streaming and shaders a moment, then select, edit, shoot and report.
	GetWorldTimerManager().SetTimer(SelfTestTimer, this, &AMapBuilderController::SelfTestEdit, 8.f, false);
}

void AMapBuilderController::SelfTestEdit()
{
	// As a player would: A on what's under the crosshair, X to grab, rotate twice (RB RB), lift (D-pad up), place.
	UpdateTarget();
	PressA();
	PressX();
	PressRB();
	PressRB();
	PressDPadUp();
	UpdateGrab();
	PressX();
	Edits->Save(FPaths::Combine(SelfTestFolder, TEXT("builder.edits.json")), GetLevelPath());
	// Then open the Edit menu with the stick pointing at Duplicate, for the screenshot.
	PressLB();
	RadialChoice = 0;
	GetWorldTimerManager().SetTimer(SelfTestTimer, this, &AMapBuilderController::SelfTestShot, 1.f, false);
}

void AMapBuilderController::SelfTestShot()
{
	FScreenshotRequest::RequestScreenshot(FPaths::Combine(SelfTestFolder, TEXT("builder.png")), false, false);
	GetWorldTimerManager().SetTimer(SelfTestTimer, this, &AMapBuilderController::SelfTestReport, 3.f, false);
}

void AMapBuilderController::SelfTestReport()
{
	TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	TArray<TSharedPtr<FJsonValue>> Selected;
	for (AActor* A : GetSelectedActors())
	{
		TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
		Item->SetStringField(TEXT("name"), A->GetName());
		Item->SetStringField(TEXT("class"), A->GetClass()->GetPathName());
		Item->SetStringField(TEXT("location"), A->GetActorLocation().ToString());
		Item->SetStringField(TEXT("rotation"), A->GetActorRotation().ToString());
		Selected.Add(MakeShared<FJsonValueObject>(Item));
	}
	Report->SetArrayField(TEXT("selection"), Selected);
	Report->SetStringField(TEXT("level"), GetLevelPath());
	Report->SetStringField(TEXT("radial"), RadialTitle);
	// Raw controller input, to tell drift from a connected pad apart from no pad at all.
	TSharedRef<FJsonObject> Input = MakeShared<FJsonObject>();
	for (const FKey& K : { EKeys::Gamepad_LeftX, EKeys::Gamepad_LeftY, EKeys::Gamepad_RightX, EKeys::Gamepad_RightY,
	                       EKeys::Gamepad_LeftTriggerAxis, EKeys::Gamepad_RightTriggerAxis })
	{
		Input->SetNumberField(K.ToString(), GetInputAnalogKeyState(K));
	}
	Report->SetObjectField(TEXT("input"), Input);
	FString Text;
	FJsonSerializer::Serialize(Report, TJsonWriterFactory<>::Create(&Text));
	FFileHelper::SaveStringToFile(Text, *FPaths::Combine(SelfTestFolder, TEXT("builder.json")));
	ConsoleCommand(TEXT("quit"));
}

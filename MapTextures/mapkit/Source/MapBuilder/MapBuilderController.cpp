#include "MapBuilderController.h"

#include "DrawDebugHelpers.h"
#include "Engine/World.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/PlatformProcess.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "TimerManager.h"
#include "UnrealClient.h"

#include "MapBuilderEdits.h"
#include "MapBuilderPawn.h"

static const FColor AxisColors[3] = { FColor(235, 60, 60), FColor(80, 220, 80), FColor(70, 120, 255) };
static const FColor Highlight(255, 190, 40);

AMapBuilderController::AMapBuilderController()
{
	bShowMouseCursor = true;
}

void AMapBuilderController::BeginPlay()
{
	Super::BeginPlay();
	Edits = NewObject<UMapBuilderEdits>(this);
	StopLooking();  // cursor mode

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
	In->BindKey(EKeys::RightMouseButton, IE_Pressed, this, &AMapBuilderController::StartLooking);
	In->BindKey(EKeys::RightMouseButton, IE_Released, this, &AMapBuilderController::StopLooking);
	In->BindKey(EKeys::LeftMouseButton, IE_Pressed, this, &AMapBuilderController::LeftDown);
	In->BindKey(EKeys::LeftMouseButton, IE_Released, this, &AMapBuilderController::LeftUp);
	In->BindKey(EKeys::W, IE_Pressed, this, &AMapBuilderController::MoveTool);
	In->BindKey(EKeys::E, IE_Pressed, this, &AMapBuilderController::RotateTool);
	In->BindKey(EKeys::R, IE_Pressed, this, &AMapBuilderController::ScaleTool);
	In->BindKey(EKeys::G, IE_Pressed, this, &AMapBuilderController::CycleGrid);
	In->BindKey(EKeys::H, IE_Pressed, this, &AMapBuilderController::ToggleAngleSnap);
	In->BindKey(EKeys::Delete, IE_Pressed, this, &AMapBuilderController::DeleteSelection);
	In->BindKey(EKeys::D, IE_Pressed, this, &AMapBuilderController::DuplicateSelection);
	In->BindKey(EKeys::Z, IE_Pressed, this, &AMapBuilderController::UndoEdit);
	In->BindKey(EKeys::Y, IE_Pressed, this, &AMapBuilderController::RedoEdit);
	In->BindKey(EKeys::End, IE_Pressed, this, &AMapBuilderController::DropToFloor);
	In->BindKey(EKeys::S, IE_Pressed, this, &AMapBuilderController::SaveKey);
	In->BindKey(EKeys::B, IE_Pressed, this, &AMapBuilderController::BuildAndPlay);
	In->BindKey(EKeys::F, IE_Pressed, this, &AMapBuilderController::FrameSelection);
	In->BindKey(EKeys::Escape, IE_Pressed, this, &AMapBuilderController::ClearSelection);
	In->BindKey(EKeys::MouseScrollUp, IE_Pressed, this, &AMapBuilderController::SpeedUp);
	In->BindKey(EKeys::MouseScrollDown, IE_Pressed, this, &AMapBuilderController::SlowDown);
}

void AMapBuilderController::PlayerTick(float DeltaTime)
{
	Super::PlayerTick(DeltaTime);
	if (bLooking)
	{
		float X = 0.f, Y = 0.f;
		GetInputMouseDelta(X, Y);
		AddYawInput(X);
		AddPitchInput(-Y);
		Fly(DeltaTime);
	}
	if (DragHandle >= 0)
	{
		Drag();
	}
	DrawSelection();
	DrawHandles();
}

bool AMapBuilderController::Ctrl() const
{
	return IsInputKeyDown(EKeys::LeftControl) || IsInputKeyDown(EKeys::RightControl);
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

// ---------------------------------------------------------------- camera

void AMapBuilderController::StartLooking()
{
	if (DragHandle >= 0)
	{
		return;
	}
	bLooking = true;
	bShowMouseCursor = false;
	SetInputMode(FInputModeGameOnly());
}

void AMapBuilderController::StopLooking()
{
	bLooking = false;
	bShowMouseCursor = true;
	FInputModeGameAndUI Mode;
	Mode.SetHideCursorDuringCapture(false);
	Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
	SetInputMode(Mode);
}

void AMapBuilderController::Fly(float DeltaTime)
{
	APawn* P = GetPawn();
	if (!P)
	{
		return;
	}
	const FRotationMatrix View(GetControlRotation());
	const float Boost = IsInputKeyDown(EKeys::LeftShift) ? 3.f : 1.f;
	auto Axis = [this](FKey Plus, FKey Minus) { return (IsInputKeyDown(Plus) ? 1.f : 0.f) - (IsInputKeyDown(Minus) ? 1.f : 0.f); };
	P->AddMovementInput(View.GetUnitAxis(EAxis::X), Axis(EKeys::W, EKeys::S) * Boost);
	P->AddMovementInput(View.GetUnitAxis(EAxis::Y), Axis(EKeys::D, EKeys::A) * Boost);
	P->AddMovementInput(FVector::UpVector, Axis(EKeys::E, EKeys::Q) * Boost);
}

float AMapBuilderController::GetSpeed() const
{
	const AMapBuilderPawn* P = Cast<AMapBuilderPawn>(GetPawn());
	return P ? P->GetSpeed() : 0.f;
}

void AMapBuilderController::SpeedUp()
{
	if (AMapBuilderPawn* P = Cast<AMapBuilderPawn>(GetPawn()))
	{
		P->ScaleSpeed(1.25f);
	}
}

void AMapBuilderController::SlowDown()
{
	if (AMapBuilderPawn* P = Cast<AMapBuilderPawn>(GetPawn()))
	{
		P->ScaleSpeed(0.8f);
	}
}

void AMapBuilderController::FrameSelection()
{
	if (bLooking)
	{
		return;
	}
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

// ---------------------------------------------------------------- selection

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

bool AMapBuilderController::CanSelect(const AActor* Actor) const
{
	if (!Actor || Actor == GetPawn() || Actor->IsA<AWorldSettings>() || UMapBuilderEdits::IsDeleted(Actor))
	{
		return false;
	}
	// The ground is edited with terrain tools, not selected as an object.
	return !Actor->GetClass()->GetName().Contains(TEXT("Landscape"));
}

static AActor* PickAt(APlayerController* PC, FVector2D ScreenPosition, const TArray<AActor*>& Ignore, FHitResult* OutHit = nullptr)
{
	FVector Origin, Direction;
	if (!PC->DeprojectScreenPositionToWorld(ScreenPosition.X, ScreenPosition.Y, Origin, Direction))
	{
		return nullptr;
	}
	FCollisionQueryParams Params(SCENE_QUERY_STAT(MapBuilderPick), true, PC->GetPawn());
	Params.AddIgnoredActors(Ignore);
	FHitResult Hit;
	if (!PC->GetWorld()->LineTraceSingleByChannel(Hit, Origin, Origin + Direction * 200000.f, ECC_Visibility, Params))
	{
		return nullptr;
	}
	if (OutHit)
	{
		*OutHit = Hit;
	}
	return Hit.GetActor();
}

AActor* AMapBuilderController::SelectAt(FVector2D ScreenPosition, bool bAdd)
{
	AActor* Picked = PickAt(this, ScreenPosition, {});
	if (!bAdd)
	{
		Selection.Reset();
	}
	if (!CanSelect(Picked))
	{
		return nullptr;
	}
	if (bAdd && Selection.Contains(Picked))
	{
		Selection.Remove(Picked);  // Ctrl+click toggles
		return nullptr;
	}
	Selection.AddUnique(Picked);
	return Picked;
}

void AMapBuilderController::ClearSelection()
{
	if (!bLooking)
	{
		Selection.Reset();
	}
}

// ---------------------------------------------------------------- handles and dragging

FVector AMapBuilderController::Pivot() const
{
	const TArray<AActor*> Actors = GetSelectedActors();
	FVector Sum = FVector::ZeroVector;
	for (AActor* A : Actors)
	{
		Sum += A->GetActorLocation();
	}
	return Actors.Num() ? Sum / Actors.Num() : FVector::ZeroVector;
}

float AMapBuilderController::HandleLength() const
{
	FVector CamLoc;
	FRotator CamRot;
	GetPlayerViewPoint(CamLoc, CamRot);
	return FMath::Max(20.f, FVector::Dist(CamLoc, Pivot()) * 0.12f);
}

static float DistanceToSegment(const FVector2D& P, const FVector2D& A, const FVector2D& B)
{
	const FVector2D AB = B - A;
	const float T = FMath::Clamp(FVector2D::DotProduct(P - A, AB) / FMath::Max(AB.SizeSquared(), 1.f), 0.f, 1.f);
	return FVector2D::Distance(P, A + AB * T);
}

int32 AMapBuilderController::HandleUnderMouse() const
{
	if (!GetSelectedActors().Num())
	{
		return -1;
	}
	float MX = 0.f, MY = 0.f;
	if (!GetMousePosition(MX, MY))
	{
		return -1;
	}
	const FVector2D Mouse(MX, MY);
	const FVector P = Pivot();
	FVector2D P0;
	if (!ProjectWorldLocationToScreen(P, P0))
	{
		return -1;
	}
	if (FVector2D::Distance(Mouse, P0) < 12.f)
	{
		return 3;
	}
	const float Len = HandleLength();
	int32 Best = -1;
	float BestDistance = 10.f;
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		FVector2D P1;
		if (ProjectWorldLocationToScreen(P + FVector(Axis == 0, Axis == 1, Axis == 2) * Len, P1))
		{
			const float D = DistanceToSegment(Mouse, P0, P1);
			if (D < BestDistance)
			{
				BestDistance = D;
				Best = Axis;
			}
		}
	}
	return Best;
}

void AMapBuilderController::LeftDown()
{
	if (bLooking)
	{
		return;
	}
	float MX = 0.f, MY = 0.f;
	GetMousePosition(MX, MY);
	const FVector2D Mouse(MX, MY);
	int32 Handle = Ctrl() ? -1 : HandleUnderMouse();
	if (Handle < 0)
	{
		AActor* Hit = PickAt(this, Mouse, {});
		if (Hit && !Ctrl() && Selection.Contains(Hit))
		{
			Handle = 4;  // drag the selected object itself over surfaces
		}
		else
		{
			SelectAt(Mouse, Ctrl());
			return;
		}
	}
	const TArray<AActor*> Actors = GetSelectedActors();
	DragHandle = Handle;
	DragStartMouse = Mouse;
	DragPivot = Pivot();
	DragStart.Reset();
	for (AActor* A : Actors)
	{
		DragStart.Add(A->GetActorTransform());
	}
	Edits->BeginTransform(Actors);
}

void AMapBuilderController::LeftUp()
{
	if (DragHandle >= 0)
	{
		DragHandle = -1;
		Edits->EndTransform();
	}
}

void AMapBuilderController::Drag()
{
	float MX = 0.f, MY = 0.f;
	GetMousePosition(MX, MY);
	const FVector2D Mouse(MX, MY), Delta = Mouse - DragStartMouse;
	const TArray<AActor*> Actors = GetSelectedActors();
	if (Actors.Num() != DragStart.Num() || (DragHandle == 4 && Delta.Size() < 3.f))
	{
		return;
	}
	const float Len = HandleLength();

	if (DragHandle == 4)
	{
		// Slide: keep the pivot's height above the selection's base, standing on whatever is under the cursor.
		FBox Bounds(ForceInit);
		for (int32 i = 0; i < Actors.Num(); ++i)
		{
			Bounds += Actors[i]->GetComponentsBoundingBox(true).ShiftBy(DragStart[i].GetLocation() - Actors[i]->GetActorLocation());
		}
		FHitResult Hit;
		if (!PickAt(this, Mouse, Actors, &Hit))
		{
			return;
		}
		FVector Target = Hit.ImpactPoint + FVector(0, 0, DragPivot.Z - Bounds.Min.Z);
		if (Grid > 0.f)
		{
			Target.X = FMath::GridSnap(Target.X, Grid);
			Target.Y = FMath::GridSnap(Target.Y, Grid);
		}
		const FVector Move = Target - DragPivot;
		for (int32 i = 0; i < Actors.Num(); ++i)
		{
			Actors[i]->SetActorLocation(DragStart[i].GetLocation() + Move);
		}
		return;
	}

	// Along a handle: how far the mouse moved along the handle's direction on screen, in world units.
	const FVector Axis = DragHandle < 3 ? FVector(DragHandle == 0, DragHandle == 1, DragHandle == 2) : FVector::UpVector;
	FVector2D P0, P1;
	ProjectWorldLocationToScreen(DragPivot, P0);
	ProjectWorldLocationToScreen(DragPivot + Axis * Len, P1);
	const FVector2D ScreenAxis = P1 - P0;
	const float Pixels = FMath::Max(ScreenAxis.Size(), 1.f);
	const float Along = FVector2D::DotProduct(Delta, ScreenAxis / Pixels) / Pixels * Len;

	for (int32 i = 0; i < Actors.Num(); ++i)
	{
		FTransform T = DragStart[i];
		switch (Tool)
		{
		case EMapBuilderTool::Move:
		{
			if (DragHandle == 3)
			{
				break;
			}
			const float Distance = Grid > 0.f ? FMath::GridSnap(Along, Grid) : Along;
			T.SetLocation(T.GetLocation() + Axis * Distance);
			break;
		}
		case EMapBuilderTool::Rotate:
		{
			if (DragHandle == 3)
			{
				break;
			}
			float Degrees = (Delta.X - Delta.Y) * 0.5f;
			if (bAngleSnap)
			{
				Degrees = FMath::GridSnap(Degrees, 15.f);
			}
			const FQuat Turn(Axis, FMath::DegreesToRadians(Degrees));
			T.SetLocation(DragPivot + Turn.RotateVector(T.GetLocation() - DragPivot));
			T.SetRotation(Turn * T.GetRotation());
			break;
		}
		case EMapBuilderTool::Scale:
		{
			const float Factor = DragHandle == 3 ? FMath::Max(0.05f, 1.f + (Delta.X - Delta.Y) * 0.005f)
			                                      : FMath::Max(0.05f, 1.f + Along / Len);
			FVector S = T.GetScale3D();
			if (DragHandle == 3)
			{
				S *= Factor;
			}
			else
			{
				S[DragHandle] *= Factor;
			}
			T.SetScale3D(S);
			break;
		}
		}
		Actors[i]->SetActorTransform(T);
	}
}

void AMapBuilderController::DrawSelection() const
{
	for (AActor* A : GetSelectedActors())
	{
		const FBox Box = A->GetComponentsBoundingBox(true);
		DrawDebugBox(GetWorld(), Box.GetCenter(), Box.GetExtent(), Highlight, false, -1.f, SDPG_Foreground, 1.5f);
	}
}

void AMapBuilderController::DrawHandles() const
{
	if (!GetSelectedActors().Num())
	{
		return;
	}
	const FVector P = Pivot();
	const float Len = HandleLength();
	const int32 Hot = DragHandle >= 0 ? DragHandle : (bLooking ? -1 : HandleUnderMouse());
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		const FVector End = P + FVector(Axis == 0, Axis == 1, Axis == 2) * Len;
		const FColor C = Hot == Axis ? FColor::Yellow : AxisColors[Axis];
		switch (Tool)
		{
		case EMapBuilderTool::Move:
			DrawDebugDirectionalArrow(GetWorld(), P, End, Len * 0.25f, C, false, -1.f, SDPG_Foreground, Len * 0.025f);
			break;
		case EMapBuilderTool::Rotate:
			DrawDebugCircle(GetWorld(), P, Len * 0.8f, 32, C, false, -1.f, SDPG_Foreground, Len * 0.02f,
				FVector(Axis == 1, Axis == 2, Axis == 0), FVector(Axis == 2, Axis == 0, Axis == 1), false);
			DrawDebugLine(GetWorld(), P, End, C, false, -1.f, SDPG_Foreground, Len * 0.02f);
			break;
		case EMapBuilderTool::Scale:
			DrawDebugLine(GetWorld(), P, End, C, false, -1.f, SDPG_Foreground, Len * 0.025f);
			DrawDebugSolidBox(GetWorld(), End, FVector(Len * 0.05f), C, false, -1.f, SDPG_Foreground);
			break;
		}
	}
	DrawDebugSolidBox(GetWorld(), P, FVector(Len * 0.04f), Hot == 3 ? FColor::Yellow : FColor::White, false, -1.f, SDPG_Foreground);
}

// ---------------------------------------------------------------- edit commands

void AMapBuilderController::CycleGrid()
{
	if (bLooking)
	{
		return;
	}
	static const float Steps[] = { 0.f, 10.f, 25.f, 50.f, 100.f, 250.f };
	int32 i = 0;
	while (i < UE_ARRAY_COUNT(Steps) && Steps[i] != Grid)
	{
		++i;
	}
	Grid = Steps[(i + 1) % UE_ARRAY_COUNT(Steps)];
	SetStatus(Grid > 0.f ? FString::Printf(TEXT("Grid %.0f cm"), Grid) : TEXT("Grid off"));
}

void AMapBuilderController::ToggleAngleSnap()
{
	if (!bLooking)
	{
		bAngleSnap = !bAngleSnap;
		SetStatus(bAngleSnap ? TEXT("Angle snap 15 degrees") : TEXT("Angle snap off"));
	}
}

void AMapBuilderController::DeleteSelection()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	if (!bLooking && Actors.Num())
	{
		Edits->Delete(Actors);
		Selection.Reset();
		SetStatus(FString::Printf(TEXT("Deleted %d"), Actors.Num()));
	}
}

void AMapBuilderController::DuplicateSelection()
{
	if (bLooking || !Ctrl())
	{
		return;
	}
	const TArray<AActor*> Actors = GetSelectedActors();
	if (!Actors.Num())
	{
		return;
	}
	const TArray<AActor*> Copies = Edits->Duplicate(Actors, FVector(Grid > 0.f ? Grid * 2.f : 100.f, 0.f, 0.f));
	Selection.Reset();
	for (AActor* A : Copies)
	{
		Selection.Add(A);
	}
	SetStatus(FString::Printf(TEXT("Duplicated %d"), Copies.Num()));
}

void AMapBuilderController::UndoEdit()
{
	if (!bLooking && Ctrl())
	{
		SetStatus(Edits->Undo() ? TEXT("Undo") : TEXT("Nothing to undo"));
	}
}

void AMapBuilderController::RedoEdit()
{
	if (!bLooking && Ctrl())
	{
		SetStatus(Edits->Redo() ? TEXT("Redo") : TEXT("Nothing to redo"));
	}
}

void AMapBuilderController::DropToFloor()
{
	const TArray<AActor*> Actors = GetSelectedActors();
	if (bLooking || !Actors.Num())
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

bool AMapBuilderController::Save()
{
	const bool bOk = Edits->Save(GetEditsFile(), GetLevelPath());
	SetStatus(bOk ? FString::Printf(TEXT("Saved %s"), *GetEditsFile()) : TEXT("Could not save"));
	return bOk;
}

void AMapBuilderController::SaveKey()
{
	if (!bLooking && Ctrl())
	{
		Save();
	}
}

void AMapBuilderController::BuildAndPlay()
{
	if (bLooking || !Ctrl())
	{
		return;
	}
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
	ConsoleCommand(TEXT("quit"));
}

// ---------------------------------------------------------------- self-test

void AMapBuilderController::RunSelfTest()
{
	// Give streaming and shaders a moment, then select, edit, shoot and report.
	GetWorldTimerManager().SetTimer(SelfTestTimer, this, &AMapBuilderController::SelfTestSelect, 8.f, false);
}

void AMapBuilderController::SelfTestSelect()
{
	int32 W = 0, H = 0;
	GetViewportSize(W, H);
	SelectAt(FVector2D(W * 0.5f, H * 0.5f), false);
	GetWorldTimerManager().SetTimer(SelfTestTimer, this, &AMapBuilderController::SelfTestEdit, 1.f, false);
}

void AMapBuilderController::SelfTestEdit()
{
	// Lift the selection 300 cm, copy it 400 cm along X, undo and redo the copy, delete nothing, save.
	const TArray<AActor*> Actors = GetSelectedActors();
	if (Actors.Num())
	{
		Edits->BeginTransform(Actors);
		for (AActor* A : Actors)
		{
			A->AddActorWorldOffset(FVector(0, 0, 300));
		}
		Edits->EndTransform();
		Edits->Duplicate(Actors, FVector(400, 0, 0));
		Edits->Undo();
		Edits->Redo();
	}
	Edits->Save(FPaths::Combine(SelfTestFolder, TEXT("builder.edits.json")), GetLevelPath());
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
		Selected.Add(MakeShared<FJsonValueObject>(Item));
	}
	Report->SetArrayField(TEXT("selection"), Selected);
	Report->SetStringField(TEXT("level"), GetLevelPath());
	if (GetPawn())
	{
		Report->SetStringField(TEXT("camera"), GetPawn()->GetActorLocation().ToString());
	}
	FString Text;
	FJsonSerializer::Serialize(Report, TJsonWriterFactory<>::Create(&Text));
	FFileHelper::SaveStringToFile(Text, *FPaths::Combine(SelfTestFolder, TEXT("builder.json")));
	ConsoleCommand(TEXT("quit"));
}

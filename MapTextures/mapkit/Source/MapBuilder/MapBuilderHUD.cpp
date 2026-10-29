#include "MapBuilderHUD.h"

#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Misc/Paths.h"

#include "MapBuilderController.h"
#include "MapBuilderEdits.h"

static const FLinearColor TextColor(0.95f, 0.95f, 0.95f), Dim(0.7f, 0.7f, 0.7f), Accent(1.f, 0.75f, 0.2f);

static void Centered(AHUD* Hud, UCanvas* Canvas, UFont* Font, const FString& S, float X, float Y, const FLinearColor& C, float Scale)
{
	float W = 0.f, H = 0.f;
	Canvas->TextSize(Font, S, W, H, Scale, Scale);
	Hud->DrawText(S, C, X - W * 0.5f, Y - H * 0.5f, Font, Scale);
}

void AMapBuilderHUD::DrawHUD()
{
	Super::DrawHUD();
	const AMapBuilderController* PC = Cast<AMapBuilderController>(GetOwningPlayerController());
	if (!PC || !Canvas)
	{
		return;
	}
	UFont* Font = GEngine->GetMediumFont();
	const float CX = Canvas->ClipX * 0.5f, CY = Canvas->ClipY * 0.5f;

	// Top line: where you are and how things snap.
	const UMapBuilderEdits* Edits = PC->GetEdits();
	const FString Grid = PC->GetGrid() > 0.f ? FString::Printf(TEXT("grid %.0f cm"), PC->GetGrid()) : TEXT("grid off");
	const FString Step = FString::Printf(TEXT("rotation step %.0f"), PC->GetAngleSnap() > 0.f ? PC->GetAngleSnap() : 1.f);
	DrawText(FString::Printf(TEXT("MAP BUILDER   %s   %s   %s   speed %.0f   %d edits%s"), *FPaths::GetBaseFilename(PC->GetLevelPath()),
		*Grid, *Step, PC->GetSpeed(), Edits ? Edits->Count() : 0, Edits && Edits->IsDirty() ? TEXT(" (unsaved)") : TEXT("")),
		Accent, 20.f, 16.f, Font, 1.f);

	// What the buttons do right now.
	FString Hint;
	if (PC->GetRadialItems().Num())
	{
		Hint = TEXT("Right stick: point at an option");
	}
	else if (PC->IsGrabbing())
	{
		Hint = FString::Printf(TEXT("A / X: place   B: put back   LB / RB: rotate (%s)   R3: turn / tilt / roll   D-pad: up/down raise, left/right size"),
			PC->GetGrabAxisName());
	}
	else
	{
		Hint = TEXT("A: select   R3: add to selection   X: grab   Y: duplicate   B: clear   D-pad: undo / redo / speed   LB: edit   RB: settings   Menu: file");
	}
	DrawText(Hint, Dim, 20.f, Canvas->ClipY - 40.f, Font, 0.85f);

	// Status message, for a few seconds.
	if (!PC->GetStatus().IsEmpty() && FPlatformTime::Seconds() - PC->GetStatusTime() < 3.0)
	{
		Centered(this, Canvas, Font, PC->GetStatus(), CX, Canvas->ClipY - 90.f, Accent, 1.1f);
	}

	// What's selected / aimed at.
	const TArray<AActor*> Sel = PC->GetSelectedActors();
	float Y = 46.f;
	for (int32 i = 0; i < Sel.Num() && i < 5; ++i, Y += 22.f)
	{
		DrawText(FString::Printf(TEXT("%s  (%s)"), *Sel[i]->GetName(), *Sel[i]->GetClass()->GetName()), TextColor, 20.f, Y, Font, 0.85f);
	}
	if (Sel.Num() > 5)
	{
		DrawText(FString::Printf(TEXT("... and %d more"), Sel.Num() - 5), TextColor, 20.f, Y, Font, 0.85f);
	}

	// Radial menu, or the crosshair.
	const TArray<FMapBuilderRadialItem>& Items = PC->GetRadialItems();
	if (Items.Num())
	{
		const float Radius = FMath::Min(Canvas->ClipX, Canvas->ClipY) * 0.28f;
		DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.45f), CX - Radius * 1.45f, CY - Radius * 1.25f, Radius * 2.9f, Radius * 2.5f);
		Centered(this, Canvas, Font, PC->GetRadialTitle().ToUpper(), CX, CY, Accent, 1.3f);
		for (int32 i = 0; i < Items.Num(); ++i)
		{
			const float Angle = FMath::DegreesToRadians(360.f * i / Items.Num());
			const float X = CX + FMath::Sin(Angle) * Radius, Yi = CY - FMath::Cos(Angle) * Radius;
			const bool bChosen = i == PC->GetRadialChoice();
			if (bChosen)
			{
				float W = 0.f, H = 0.f;
				Canvas->TextSize(Font, Items[i].Label, W, H, 1.2f, 1.2f);
				DrawRect(FLinearColor(1.f, 0.75f, 0.2f, 0.35f), X - W * 0.5f - 12.f, Yi - H * 0.5f - 6.f, W + 24.f, H + 12.f);
			}
			Centered(this, Canvas, Font, Items[i].Label, X, Yi, bChosen ? FLinearColor::White : TextColor, bChosen ? 1.2f : 1.f);
		}
	}
	else
	{
		const FLinearColor C = PC->IsGrabbing() ? Accent : (PC->GetTarget() ? FLinearColor::White : Dim);
		DrawLine(CX - 10.f, CY, CX - 3.f, CY, C, 2.f);
		DrawLine(CX + 3.f, CY, CX + 10.f, CY, C, 2.f);
		DrawLine(CX, CY - 10.f, CX, CY - 3.f, C, 2.f);
		DrawLine(CX, CY + 3.f, CX, CY + 10.f, C, 2.f);
		if (const AActor* T = PC->GetTarget())
		{
			Centered(this, Canvas, Font, T->GetName(), CX, CY + 28.f, Dim, 0.8f);
		}
	}
}

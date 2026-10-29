#include "MapBuilderHUD.h"

#include "CanvasItem.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"
#include "Misc/Paths.h"

#include "MapBuilderController.h"
#include "MapBuilderEdits.h"

static const FLinearColor White(0.96f, 0.96f, 0.96f), Dim(0.72f, 0.74f, 0.78f), Accent(1.f, 0.66f, 0.12f);
static const FLinearColor Panel(0.004f, 0.005f, 0.008f, 0.93f), PanelEdge(1.f, 1.f, 1.f, 0.3f);

void AMapBuilderHUD::Text(const FString& S, float X, float Y, const FLinearColor& Color, float Size, bool bCentre) const
{
	UFont* Font = GEngine->GetLargeFont();
	const float Scale = Size / 16.f * UI;  // the large font is drawn at ~16 px
	FCanvasTextItem Item(FVector2D(X, Y), FText::FromString(S), Font, Color);
	Item.Scale = FVector2D(Scale, Scale);
	Item.EnableShadow(FLinearColor(0.f, 0.f, 0.f, 0.85f), FVector2D(2.f, 2.f) * UI);
	if (bCentre)
	{
		Item.bCentreX = true;
		Item.bCentreY = true;
	}
	Canvas->DrawItem(Item);
}

void AMapBuilderHUD::Wedge(FVector2D Centre, float Inner, float Outer, float From, float To, const FLinearColor& Color) const
{
	// Angles in degrees, 0 at the top, clockwise. A strip of quads (two triangles each) between the two radii.
	const int32 Steps = FMath::Max(2, FMath::CeilToInt((To - From) / 4.f));
	TArray<FCanvasUVTri> Tris;
	auto At = [&](float Deg, float R) {
		const float A = FMath::DegreesToRadians(Deg);
		return Centre + FVector2D(FMath::Sin(A), -FMath::Cos(A)) * R;
	};
	for (int32 i = 0; i < Steps; ++i)
	{
		const float A0 = FMath::Lerp(From, To, (float)i / Steps), A1 = FMath::Lerp(From, To, (float)(i + 1) / Steps);
		const FVector2D I0 = At(A0, Inner), I1 = At(A1, Inner), O0 = At(A0, Outer), O1 = At(A1, Outer);
		FCanvasUVTri T1, T2;
		T1.V0_Pos = I0; T1.V1_Pos = O0; T1.V2_Pos = O1;
		T2.V0_Pos = I0; T2.V1_Pos = O1; T2.V2_Pos = I1;
		T1.V0_Color = T1.V1_Color = T1.V2_Color = Color;
		T2.V0_Color = T2.V1_Color = T2.V2_Color = Color;
		Tris.Add(T1);
		Tris.Add(T2);
	}
	FCanvasTriangleItem Item(Tris, GWhiteTexture);
	Item.BlendMode = SE_BLEND_Translucent;
	Canvas->DrawItem(Item);
}

void AMapBuilderHUD::DrawHUD()
{
	Super::DrawHUD();
	const AMapBuilderController* PC = Cast<AMapBuilderController>(GetOwningPlayerController());
	if (!PC || !Canvas)
	{
		return;
	}
	UI = Canvas->ClipY / 1080.f;
	const float Margin = 28.f * UI;

	// Top bar: map, snapping, speed, edits.
	const UMapBuilderEdits* Edits = PC->GetEdits();
	DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.6f), 0.f, 0.f, Canvas->ClipX, 60.f * UI);
	const FString Grid = PC->GetGrid() > 0.f ? FString::Printf(TEXT("Grid %.0f cm"), PC->GetGrid()) : TEXT("Grid off");
	const FString Step = FString::Printf(TEXT("Rotation %.0f°"), PC->GetAngleSnap() > 0.f ? PC->GetAngleSnap() : 1.f);
	Text(TEXT("MAP BUILDER"), Margin, 13.f * UI, Accent, 22.f);
	Text(FString::Printf(TEXT("%s      %s      %s      Speed %.0f      %d edits%s"), *FPaths::GetBaseFilename(PC->GetLevelPath()),
		*Grid, *Step, PC->GetSpeed(), Edits ? Edits->Count() : 0, Edits && Edits->IsDirty() ? TEXT(" (unsaved)") : TEXT("")),
		Margin + 250.f * UI, 13.f * UI, White, 22.f);

	// Selection list (left).
	const TArray<AActor*> Sel = PC->GetSelectedActors();
	float Y = 72.f * UI;
	for (int32 i = 0; i < Sel.Num() && i < 5; ++i, Y += 30.f * UI)
	{
		Text(Sel[i]->GetName(), Margin, Y, Accent, 20.f);
	}
	if (Sel.Num() > 5)
	{
		Text(FString::Printf(TEXT("+ %d more"), Sel.Num() - 5), Margin, Y, Accent, 20.f);
	}

	// Status message, a few seconds.
	if (!PC->GetStatus().IsEmpty() && FPlatformTime::Seconds() - PC->GetStatusTime() < 3.0 && !PC->GetRadialItems().Num())
	{
		Text(PC->GetStatus(), Canvas->ClipX * 0.5f, Canvas->ClipY - 130.f * UI, Accent, 30.f, true);
	}

	// Button hints (bottom).
	FString Hint;
	if (PC->GetRadialItems().Num())
	{
		Hint = TEXT("");
	}
	else if (PC->IsGrabbing())
	{
		Hint = FString::Printf(TEXT("A  place     B  put back     LB / RB  rotate (%s)     R3  turn / tilt / roll     D-pad  height / size"),
			PC->GetGrabAxisName());
	}
	else
	{
		Hint = TEXT("A  select     X  grab     Y  duplicate     B  clear     R3  add     D-pad  undo / redo / speed     LB  edit     RB  settings     Menu  file");
	}
	if (!Hint.IsEmpty())
	{
		DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.45f), 0.f, Canvas->ClipY - 56.f * UI, Canvas->ClipX, 56.f * UI);
		Text(Hint, Canvas->ClipX * 0.5f, Canvas->ClipY - 28.f * UI, White, 22.f, true);
	}

	if (PC->GetRadialItems().Num())
	{
		DrawRadial(PC);
	}
	else
	{
		DrawCrosshair(PC);
	}
}

void AMapBuilderHUD::DrawCrosshair(const AMapBuilderController* PC)
{
	const float CX = Canvas->ClipX * 0.5f, CY = Canvas->ClipY * 0.5f;
	const FLinearColor C = PC->IsGrabbing() ? Accent : (PC->GetTarget() ? White : Dim);
	const float In = 5.f * UI, Out = 16.f * UI, T = 2.5f * UI;
	for (const FVector2D D : { FVector2D(1, 0), FVector2D(-1, 0), FVector2D(0, 1), FVector2D(0, -1) })
	{
		DrawLine(CX + D.X * In + 1, CY + D.Y * In + 1, CX + D.X * Out + 1, CY + D.Y * Out + 1, FLinearColor(0, 0, 0, 0.7f), T);
		DrawLine(CX + D.X * In, CY + D.Y * In, CX + D.X * Out, CY + D.Y * Out, C, T);
	}
	if (const AActor* Target = PC->GetTarget())
	{
		if (!PC->IsGrabbing())
		{
			Text(Target->GetName(), CX, CY + 40.f * UI, White, 20.f, true);
		}
	}
}

void AMapBuilderHUD::DrawRadial(const AMapBuilderController* PC)
{
	const TArray<FMapBuilderRadialItem>& Items = PC->GetRadialItems();
	const int32 N = Items.Num();
	const FVector2D C(Canvas->ClipX * 0.5f, Canvas->ClipY * 0.5f);
	const float Outer = 400.f * UI, Inner = 150.f * UI, Gap = 1.2f;
	const float Slice = 360.f / N;
	const int32 Chosen = PC->GetRadialChoice();

	// Dim the world behind it.
	DrawRect(FLinearColor(0.f, 0.f, 0.f, 0.5f), 0.f, 0.f, Canvas->ClipX, Canvas->ClipY);

	// One wedge per option, centred on its direction (option 0 at the top, clockwise); the chosen one stands out.
	for (int32 i = 0; i < N; ++i)
	{
		const float From = i * Slice - Slice * 0.5f + Gap, To = i * Slice + Slice * 0.5f - Gap;
		const bool bChosen = i == Chosen;
		Wedge(C, Inner, bChosen ? Outer + 18.f * UI : Outer, From, To, bChosen ? FLinearColor(1.f, 0.62f, 0.1f, 0.95f) : Panel);
		Wedge(C, Outer - 3.f * UI, Outer, From, To, bChosen ? FLinearColor(1.f, 0.85f, 0.5f, 1.f) : PanelEdge);
	}
	// Centre disc.
	Wedge(C, 0.f, Inner - 8.f * UI, 0.f, 360.f, FLinearColor(0.f, 0.f, 0.f, 0.95f));

	// Labels, mid-ring. Long labels shrink to fit.
	for (int32 i = 0; i < N; ++i)
	{
		const float A = FMath::DegreesToRadians(i * Slice);
		const FVector2D P = C + FVector2D(FMath::Sin(A), -FMath::Cos(A)) * (Inner + Outer) * 0.5f;
		const bool bChosen = i == Chosen;
		const float Size = FMath::Clamp(30.f - FMath::Max(0, Items[i].Label.Len() - 14) * 0.9f, 20.f, 30.f);
		Text(Items[i].Label, P.X, P.Y, bChosen ? FLinearColor(0.08f, 0.05f, 0.f) : White, bChosen ? Size + 2.f : Size, true);
	}

	// Centre: the menu, the option you're on, and what to press.
	Text(PC->GetRadialTitle().ToUpper(), C.X, C.Y - 48.f * UI, Accent, 26.f, true);
	Text(Items.IsValidIndex(Chosen) ? Items[Chosen].Label : TEXT("—"), C.X, C.Y + 2.f * UI, White, 30.f, true);
	Text(PC->IsRadialSticky() ? TEXT("A choose   B back") : TEXT("release to choose"), C.X, C.Y + 52.f * UI, Dim, 20.f, true);

	// Where the stick points.
	const FVector2D S = PC->GetRadialStick();
	if (S.Size() > 0.2f)
	{
		const FVector2D Dir = S.GetSafeNormal();
		const FVector2D Dot = C + FVector2D(Dir.X, -Dir.Y) * (Inner - 22.f * UI);
		Wedge(Dot, 0.f, 10.f * UI, 0.f, 360.f, Accent);
	}
}

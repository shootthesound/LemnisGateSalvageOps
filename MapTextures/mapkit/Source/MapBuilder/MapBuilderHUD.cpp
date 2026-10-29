#include "MapBuilderHUD.h"

#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/Font.h"

#include "MapBuilderController.h"
#include "MapBuilderEdits.h"

void AMapBuilderHUD::DrawHUD()
{
	Super::DrawHUD();
	const AMapBuilderController* PC = Cast<AMapBuilderController>(GetOwningPlayerController());
	if (!PC || !Canvas)
	{
		return;
	}
	UFont* Font = GEngine->GetSmallFont();
	const FLinearColor Text(0.95f, 0.95f, 0.95f), Dim(0.65f, 0.65f, 0.65f), Accent(1.f, 0.75f, 0.2f);
	float Y = 16.f;
	auto Line = [&](const FString& S, const FLinearColor& C) { DrawText(S, C, 16.f, Y, Font, 1.2f); Y += 20.f; };

	static const TCHAR* Tools[] = { TEXT("Move"), TEXT("Rotate"), TEXT("Scale") };
	const UMapBuilderEdits* Edits = PC->GetEdits();
	Line(FString::Printf(TEXT("MAP BUILDER   %s   %s   grid %s   angle snap %s   %d edits%s"),
		*FPaths::GetBaseFilename(PC->GetLevelPath()), Tools[(int32)PC->GetTool()],
		PC->GetGrid() > 0.f ? *FString::Printf(TEXT("%.0f"), PC->GetGrid()) : TEXT("off"), PC->IsAngleSnap() ? TEXT("on") : TEXT("off"),
		Edits ? Edits->Count() : 0, Edits && Edits->IsDirty() ? TEXT(" (unsaved)") : TEXT("")), Accent);
	Line(TEXT("Hold right mouse: look, WASD / Q E fly, Shift faster, wheel speed"), Dim);
	Line(TEXT("Click: select   Ctrl+click: add   Drag handle: move/rotate/scale   Drag object: slide over surfaces"), Dim);
	Line(TEXT("W / E / R: move / rotate / scale   G: grid   H: angle snap   End: drop to floor   F: frame"), Dim);
	Line(TEXT("Delete   Ctrl+D duplicate   Ctrl+Z / Ctrl+Y undo / redo   Ctrl+S save   Esc: clear selection"), Dim);
	Line(FString::Printf(TEXT("Speed %.0f"), PC->GetSpeed()), Dim);
	if (!PC->GetStatus().IsEmpty())
	{
		Line(PC->GetStatus(), Accent);
	}
	Y += 6.f;
	const TArray<AActor*> Sel = PC->GetSelectedActors();
	for (int32 i = 0; i < Sel.Num() && i < 6; ++i)
	{
		Line(FString::Printf(TEXT("%s  (%s)  %s"), *Sel[i]->GetName(), *Sel[i]->GetClass()->GetName(),
			*Sel[i]->GetActorLocation().ToCompactString()), Text);
	}
	if (Sel.Num() > 6)
	{
		Line(FString::Printf(TEXT("... and %d more"), Sel.Num() - 6), Text);
	}
}

// The builder's on-screen display: status line, crosshair, button hints and the radial menus.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "MapBuilderHUD.generated.h"

class AMapBuilderController;
class UFont;

UCLASS()
class MAPBUILDER_API AMapBuilderHUD : public AHUD
{
	GENERATED_BODY()
protected:
	virtual void DrawHUD() override;

private:
	// Text with a drop shadow, centred on (X, Y) if bCentre. Sizes are for a 1080-line screen and scale with it.
	void Text(const FString& S, float X, float Y, const FLinearColor& Color, float Size, bool bCentre = false) const;
	void Wedge(FVector2D Centre, float Inner, float Outer, float From, float To, const FLinearColor& Color) const;
	void DrawRadial(const AMapBuilderController* PC);
	void DrawCrosshair(const AMapBuilderController* PC);
	void DrawBrowser(const AMapBuilderController* PC);

	float UI = 1.f;  // screen height / 1080
};

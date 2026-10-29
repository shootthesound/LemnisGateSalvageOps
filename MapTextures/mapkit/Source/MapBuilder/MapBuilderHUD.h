// The builder's on-screen text: controls, speed and what's selected.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/HUD.h"
#include "MapBuilderHUD.generated.h"

UCLASS()
class MAPBUILDER_API AMapBuilderHUD : public AHUD
{
	GENERATED_BODY()
protected:
	virtual void DrawHUD() override;
};

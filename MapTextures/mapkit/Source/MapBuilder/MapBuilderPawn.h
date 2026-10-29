// The builder's camera: flies freely through the level (no collision), with an adjustable speed.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/DefaultPawn.h"
#include "MapBuilderPawn.generated.h"

UCLASS()
class MAPBUILDER_API AMapBuilderPawn : public ADefaultPawn
{
	GENERATED_BODY()
public:
	AMapBuilderPawn(const FObjectInitializer& ObjectInitializer);

	// Multiply the flying speed (mouse wheel), within sensible limits.
	void ScaleSpeed(float Factor);
	float GetSpeed() const;
};

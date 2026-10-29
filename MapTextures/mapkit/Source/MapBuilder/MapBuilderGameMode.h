// The map builder: open a level as "<level>?game=/Script/MapBuilder.MapBuilderGameMode" and edit it first-person.
#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "MapBuilderGameMode.generated.h"

UCLASS()
class MAPBUILDER_API AMapBuilderGameMode : public AGameModeBase
{
	GENERATED_BODY()
public:
	AMapBuilderGameMode();
};

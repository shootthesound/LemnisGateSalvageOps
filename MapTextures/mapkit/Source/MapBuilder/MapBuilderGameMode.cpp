#include "MapBuilderGameMode.h"

#include "MapBuilderController.h"
#include "MapBuilderHUD.h"
#include "MapBuilderPawn.h"

AMapBuilderGameMode::AMapBuilderGameMode()
{
	DefaultPawnClass = AMapBuilderPawn::StaticClass();
	PlayerControllerClass = AMapBuilderController::StaticClass();
	HUDClass = AMapBuilderHUD::StaticClass();
}

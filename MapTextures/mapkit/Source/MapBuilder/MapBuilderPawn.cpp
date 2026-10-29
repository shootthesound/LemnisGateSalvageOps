#include "MapBuilderPawn.h"

#include "Components/SphereComponent.h"
#include "GameFramework/FloatingPawnMovement.h"

AMapBuilderPawn::AMapBuilderPawn(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	bAddDefaultMovementBindings = false;  // the controller binds keys; the mouse only looks while right-dragging
	GetCollisionComponent()->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	if (UFloatingPawnMovement* Movement = Cast<UFloatingPawnMovement>(GetMovementComponent()))
	{
		Movement->MaxSpeed = 1500.f;
		Movement->Acceleration = 8000.f;
		Movement->Deceleration = 16000.f;
	}
}

void AMapBuilderPawn::ScaleSpeed(float Factor)
{
	if (UFloatingPawnMovement* Movement = Cast<UFloatingPawnMovement>(GetMovementComponent()))
	{
		Movement->MaxSpeed = FMath::Clamp(Movement->MaxSpeed * Factor, 100.f, 20000.f);
		Movement->Acceleration = Movement->MaxSpeed * 5.f;
		Movement->Deceleration = Movement->MaxSpeed * 10.f;
	}
}

float AMapBuilderPawn::GetSpeed() const
{
	const UFloatingPawnMovement* Movement = Cast<UFloatingPawnMovement>(GetMovementComponent());
	return Movement ? Movement->MaxSpeed : 0.f;
}

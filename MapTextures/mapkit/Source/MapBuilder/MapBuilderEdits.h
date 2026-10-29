// What's been changed in the builder, as a list of edits against the level it opened: objects moved, deleted, or
// added (copies of an existing object, or new parts). Undo/redo step through it. Saved as JSON, which the game's
// profile applies to the real level (for Lemnis Gate: kit.py apply), so everything the builder doesn't touch stays
// exactly as it was.
#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "MapBuilderEdits.generated.h"

UCLASS()
class MAPBUILDER_API UMapBuilderEdits : public UObject
{
	GENERATED_BODY()
public:
	// Record a change of these actors' transforms (call Begin before changing, End after).
	void BeginTransform(const TArray<AActor*>& Actors);
	void EndTransform();

	// Delete (hidden until saved, so it can be undone) or duplicate actors; both are one undo step.
	void Delete(const TArray<AActor*>& Actors);
	TArray<AActor*> Duplicate(const TArray<AActor*>& Actors, const FVector& Offset);

	bool Undo();
	bool Redo();
	int32 Count() const { return History.Num(); }
	bool IsDirty() const { return bDirty; }

	// The edits so far as JSON: { level, moved: {name: transform}, deleted: [name], added: [{name, source, transform}] }.
	FString ToJson(const FString& Level) const;
	bool Save(const FString& File, const FString& Level);

	static bool IsDeleted(const AActor* Actor);

private:
	struct FStep
	{
		enum EKind { Transform, Delete, Add } Kind = Transform;
		TArray<TWeakObjectPtr<AActor>> Actors;
		TArray<FTransform> Before, After;
	};
	void Apply(const FStep& Step, bool bForward);

	TArray<FStep> History;
	int32 Position = 0;  // steps [0, Position) are applied
	TOptional<FStep> Pending;
	bool bDirty = false;

	// Copies made in the builder: copy -> the level actor it was copied from.
	TMap<TWeakObjectPtr<AActor>, FName> Sources;
};

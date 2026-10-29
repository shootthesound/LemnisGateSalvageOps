#include "MapBuilderEdits.h"

#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

static const FName DeletedTag(TEXT("MapBuilderDeleted"));

// A running world won't move Static objects (most of a level), so anything the builder edits becomes Movable. Only
// in the builder: the saved edits are positions.
static void MakeMovable(AActor* Actor)
{
	if (USceneComponent* Root = Actor ? Actor->GetRootComponent() : nullptr)
	{
		if (Root->Mobility != EComponentMobility::Movable)
		{
			Root->SetMobility(EComponentMobility::Movable);
		}
	}
}

bool UMapBuilderEdits::IsDeleted(const AActor* Actor)
{
	return Actor && Actor->Tags.Contains(DeletedTag);
}

void UMapBuilderEdits::BeginTransform(const TArray<AActor*>& Actors)
{
	FStep Step;
	Step.Kind = FStep::Transform;
	for (AActor* A : Actors)
	{
		MakeMovable(A);
		Step.Actors.Add(A);
		Step.Before.Add(A->GetActorTransform());
	}
	Pending = Step;
}

void UMapBuilderEdits::EndTransform()
{
	if (!Pending.IsSet())
	{
		return;
	}
	FStep Step = Pending.GetValue();
	Pending.Reset();
	bool bChanged = false;
	for (int32 i = 0; i < Step.Actors.Num(); ++i)
	{
		const FTransform Now = Step.Actors[i].IsValid() ? Step.Actors[i]->GetActorTransform() : Step.Before[i];
		Step.After.Add(Now);
		bChanged |= !Now.Equals(Step.Before[i], 0.01f);
	}
	if (bChanged)
	{
		History.SetNum(Position);
		History.Add(MoveTemp(Step));
		++Position;
		bDirty = true;
	}
}

void UMapBuilderEdits::Delete(const TArray<AActor*>& Actors)
{
	FStep Step;
	Step.Kind = FStep::Delete;
	for (AActor* A : Actors)
	{
		Step.Actors.Add(A);
	}
	History.SetNum(Position);
	History.Add(Step);
	++Position;
	Apply(Step, true);
	bDirty = true;
}

TArray<AActor*> UMapBuilderEdits::Duplicate(const TArray<AActor*>& Actors, const FVector& Offset)
{
	FStep Step;
	Step.Kind = FStep::Add;
	TArray<AActor*> Copies;
	for (AActor* A : Actors)
	{
		FActorSpawnParameters Params;
		Params.Template = A;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		FTransform T = A->GetActorTransform();
		T.AddToTranslation(Offset);
		AActor* Copy = A->GetWorld()->SpawnActor(A->GetClass(), &T, Params);
		if (!Copy)
		{
			continue;
		}
		MakeMovable(Copy);
		Copy->SetActorTransform(T);  // spawning combines the template's own placement with T
		// A copy of a copy is still a copy of the level actor; a copy of a new part is another new part.
		if (const FString* Asset = Assets.Find(A))
		{
			Assets.Add(Copy, *Asset);
		}
		else
		{
			const FName* Root = Sources.Find(A);
			Sources.Add(Copy, Root ? *Root : A->GetFName());
		}
		Step.Actors.Add(Copy);
		Copies.Add(Copy);
	}
	if (Copies.Num())
	{
		History.SetNum(Position);
		History.Add(Step);
		++Position;
		bDirty = true;
	}
	return Copies;
}

AActor* UMapBuilderEdits::SpawnAsset(UWorld* World, const FString& Asset, const FTransform& Transform)
{
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AActor* Actor = nullptr;
	if (Asset.StartsWith(TEXT("mesh:")))
	{
		UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *Asset.Mid(5));
		if (!Mesh)
		{
			return nullptr;
		}
		AStaticMeshActor* M = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), Transform, Params);
		if (M)
		{
			M->GetStaticMeshComponent()->SetMobility(EComponentMobility::Movable);
			M->GetStaticMeshComponent()->SetStaticMesh(Mesh);
		}
		Actor = M;
	}
	else if (Asset.StartsWith(TEXT("class:")))
	{
		UClass* Class = LoadClass<AActor>(nullptr, *Asset.Mid(6));
		Actor = Class ? World->SpawnActor<AActor>(Class, Transform, Params) : nullptr;
		if (Actor && Actor->GetRootComponent())
		{
			Actor->GetRootComponent()->SetMobility(EComponentMobility::Movable);
		}
	}
	if (Actor)
	{
		Actor->SetActorTransform(Transform);  // spawning combines the class's own default placement with Transform
	}
	return Actor;
}

AActor* UMapBuilderEdits::AddAsset(UWorld* World, const FString& Asset, const FTransform& Transform)
{
	AActor* Actor = SpawnAsset(World, Asset, Transform);
	if (!Actor)
	{
		return nullptr;
	}
	Assets.Add(Actor, Asset);
	FStep Step;
	Step.Kind = FStep::Add;
	Step.Actors.Add(Actor);
	History.SetNum(Position);
	History.Add(Step);
	++Position;
	bDirty = true;
	return Actor;
}

void UMapBuilderEdits::Apply(const FStep& Step, bool bForward)
{
	for (int32 i = 0; i < Step.Actors.Num(); ++i)
	{
		AActor* A = Step.Actors[i].Get();
		if (!A)
		{
			continue;
		}
		switch (Step.Kind)
		{
		case FStep::Transform:
			A->SetActorTransform(bForward ? Step.After[i] : Step.Before[i]);
			break;
		case FStep::Delete:
		case FStep::Add:
		{
			// Deleting hides; undoing an add hides the copy. Either way the actor stays around for redo.
			const bool bGone = (Step.Kind == FStep::Delete) == bForward;
			A->SetActorHiddenInGame(bGone);
			A->SetActorEnableCollision(!bGone);
			if (bGone)
			{
				A->Tags.AddUnique(DeletedTag);
			}
			else
			{
				A->Tags.Remove(DeletedTag);
			}
			break;
		}
		}
	}
}

bool UMapBuilderEdits::Undo()
{
	if (Position == 0)
	{
		return false;
	}
	Apply(History[--Position], false);
	bDirty = true;
	return true;
}

bool UMapBuilderEdits::Redo()
{
	if (Position >= History.Num())
	{
		return false;
	}
	Apply(History[Position++], true);
	bDirty = true;
	return true;
}

static TSharedRef<FJsonObject> TransformJson(const FTransform& T)
{
	TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
	const FVector L = T.GetLocation(), S = T.GetScale3D();
	const FRotator R = T.Rotator();
	O->SetArrayField(TEXT("location"), { MakeShared<FJsonValueNumber>(L.X), MakeShared<FJsonValueNumber>(L.Y), MakeShared<FJsonValueNumber>(L.Z) });
	O->SetArrayField(TEXT("rotation"), { MakeShared<FJsonValueNumber>(R.Pitch), MakeShared<FJsonValueNumber>(R.Yaw), MakeShared<FJsonValueNumber>(R.Roll) });
	O->SetArrayField(TEXT("scale"), { MakeShared<FJsonValueNumber>(S.X), MakeShared<FJsonValueNumber>(S.Y), MakeShared<FJsonValueNumber>(S.Z) });
	return O;
}

FString UMapBuilderEdits::ToJson(const FString& Level) const
{
	// Net effect of the applied steps: last transform per actor, deleted level actors, live copies.
	TMap<TWeakObjectPtr<AActor>, FTransform> Moved;
	TSet<TWeakObjectPtr<AActor>> Touched;
	for (int32 s = 0; s < Position; ++s)
	{
		for (const TWeakObjectPtr<AActor>& A : History[s].Actors)
		{
			Touched.Add(A);
		}
	}
	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("level"), Level);
	TSharedRef<FJsonObject> MovedJson = MakeShared<FJsonObject>();
	TArray<TSharedPtr<FJsonValue>> Deleted, Added;
	for (const TWeakObjectPtr<AActor>& Weak : Touched)
	{
		AActor* A = Weak.Get();
		if (!A)
		{
			continue;
		}
		const FName* Source = Sources.Find(Weak);
		if (const FString* Asset = Assets.Find(Weak))
		{
			if (!IsDeleted(A))
			{
				TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
				Item->SetStringField(TEXT("name"), A->GetName());
				Item->SetStringField(TEXT("asset"), *Asset);
				Item->SetObjectField(TEXT("transform"), TransformJson(A->GetActorTransform()));
				Added.Add(MakeShared<FJsonValueObject>(Item));
			}
		}
		else if (Source)
		{
			if (!IsDeleted(A))
			{
				TSharedRef<FJsonObject> Item = MakeShared<FJsonObject>();
				Item->SetStringField(TEXT("name"), A->GetName());
				Item->SetStringField(TEXT("source"), Source->ToString());
				Item->SetObjectField(TEXT("transform"), TransformJson(A->GetActorTransform()));
				Added.Add(MakeShared<FJsonValueObject>(Item));
			}
		}
		else if (IsDeleted(A))
		{
			Deleted.Add(MakeShared<FJsonValueString>(A->GetName()));
		}
		else
		{
			MovedJson->SetObjectField(A->GetName(), TransformJson(A->GetActorTransform()));
		}
	}
	Root->SetObjectField(TEXT("moved"), MovedJson);
	Root->SetArrayField(TEXT("deleted"), Deleted);
	Root->SetArrayField(TEXT("added"), Added);
	FString Text;
	FJsonSerializer::Serialize(Root, TJsonWriterFactory<>::Create(&Text));
	return Text;
}

bool UMapBuilderEdits::Save(const FString& File, const FString& Level)
{
	if (!FFileHelper::SaveStringToFile(ToJson(Level), *File))
	{
		return false;
	}
	bDirty = false;
	return true;
}

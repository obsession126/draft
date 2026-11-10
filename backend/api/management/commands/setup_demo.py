from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from api.models import CrewProfile


class Command(BaseCommand):
    help = "Create or verify a local demo user, API token, and crew profile."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="crew")
        parser.add_argument("--password", required=True)
        parser.add_argument("--profile-id", default="crew-01")
        parser.add_argument("--display-name", default="Crew Member 01")
        parser.add_argument("--mission-name", default="Demo mission")

    def handle(self, *args, **options):
        user_model = get_user_model()
        username = options["username"]
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={"is_active": True},
        )
        if created:
            user.set_password(options["password"])
            user.save(update_fields=("password",))
        elif not user.check_password(options["password"]):
            raise CommandError(
                f"User '{username}' already exists; the supplied password did not match."
            )
        if not user.is_active:
            raise CommandError(f"User '{username}' is inactive.")

        profile, profile_created = CrewProfile.objects.get_or_create(
            profile_id=options["profile_id"],
            defaults={
                "owner": user,
                "display_name": options["display_name"],
                "mission_name": options["mission_name"],
            },
        )
        if profile.owner_id != user.id:
            raise CommandError(
                f"Profile '{profile.profile_id}' already belongs to another user."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo account ready: username={username}, profile={profile.profile_id}, "
                f"profile_created={profile_created}. Sign in through the web app with "
                "the supplied username and password."
            )
        )

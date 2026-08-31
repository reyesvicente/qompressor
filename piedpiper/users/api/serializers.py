from allauth.account.forms import UserTokenForm
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from piedpiper.users.models import User


class UserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["username", "name", "url"]

        extra_kwargs = {
            "url": {"view_name": "api:user-detail", "lookup_field": "username"},
        }


class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    def validate_username(self, value: str) -> str:
        if User.objects.filter(username__iexact=value).exists():
            msg = "A user with that username already exists."
            raise serializers.ValidationError(msg)
        return value

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            msg = "A user with that email already exists."
            raise serializers.ValidationError(msg)
        return value

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs["password_confirm"]:
            msg = "Passwords do not match."
            raise serializers.ValidationError({"password_confirm": msg})
        validate_password(attrs["password"])
        return attrs

    def create(self, validated_data: dict) -> User:
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            name=validated_data.get("name", ""),
            password=validated_data["password"],
        )


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    key = serializers.CharField()
    password = serializers.CharField(write_only=True)
    password_confirm = serializers.CharField(write_only=True)

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs["password_confirm"]:
            msg = "Passwords do not match."
            raise serializers.ValidationError({"password_confirm": msg})

        uidb36, _sep, temp_key = attrs["key"].partition("-")
        token_form = UserTokenForm(data={"uidb36": uidb36, "key": temp_key})
        if not token_form.is_valid():
            msg = "This password reset link is invalid or has expired."
            raise serializers.ValidationError({"key": msg})

        attrs["reset_user"] = token_form.reset_user
        attrs["temp_key"] = temp_key
        return attrs


class EmailConfirmSerializer(serializers.Serializer):
    key = serializers.CharField()

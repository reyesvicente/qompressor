import logging

from allauth.account.forms import ResetPasswordForm
from allauth.account.forms import ResetPasswordKeyForm
from allauth.account.models import EmailAddress
from allauth.account.models import EmailConfirmationHMAC
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.generics import CreateAPIView
from rest_framework.mixins import ListModelMixin
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.mixins import UpdateModelMixin
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from piedpiper.users.models import User

from .serializers import EmailConfirmSerializer
from .serializers import PasswordResetConfirmSerializer
from .serializers import PasswordResetRequestSerializer
from .serializers import RegisterSerializer
from .serializers import UserSerializer

logger = logging.getLogger(__name__)


class UserViewSet(RetrieveModelMixin, ListModelMixin, UpdateModelMixin, GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    lookup_field = "username"

    def get_queryset(self, *args, **kwargs):
        assert isinstance(self.request.user.id, int)
        return self.queryset.filter(id=self.request.user.id)

    @action(detail=False)
    def me(self, request):
        serializer = UserSerializer(request.user, context={"request": request})
        return Response(status=status.HTTP_200_OK, data=serializer.data)


class RegisterView(CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        email_address = EmailAddress.objects.create(
            user=user,
            email=user.email,
            primary=True,
            verified=False,
        )
        try:
            email_address.send_confirmation(request, signup=True)
        except OSError:
            # Account creation must succeed even if the mail server is
            # unreachable; the user can request another confirmation email.
            logger.exception("Failed to send confirmation email to %s", user.email)

        token, _created = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user": UserSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_201_CREATED,
        )


class PasswordResetRequestView(APIView):
    """Sends a reset email if the address is known. Always returns 200 —
    the response must not reveal whether the address has an account."""

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        form = ResetPasswordForm(data=serializer.validated_data)
        if form.is_valid():
            try:
                form.save(request)
            except OSError:
                logger.exception(
                    "Failed to send password reset email to %s",
                    serializer.validated_data["email"],
                )
        return Response(status=status.HTTP_200_OK)


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        key_form = ResetPasswordKeyForm(
            data={
                "password1": serializer.validated_data["password"],
                "password2": serializer.validated_data["password_confirm"],
            },
            user=serializer.validated_data["reset_user"],
            temp_key=serializer.validated_data["temp_key"],
        )
        if not key_form.is_valid():
            return Response(key_form.errors, status=status.HTTP_400_BAD_REQUEST)
        key_form.save()
        return Response(status=status.HTTP_200_OK)


class EmailConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = EmailConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        confirmation = EmailConfirmationHMAC.from_key(serializer.validated_data["key"])
        if confirmation is None:
            return Response(
                {"detail": "This confirmation link is invalid or has expired."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        confirmation.confirm(request)
        return Response(status=status.HTTP_200_OK)

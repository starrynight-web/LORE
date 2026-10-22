from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Organization, OrganizationMembership, OrganizationInvitation

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']

class OrganizationSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Organization
        fields = ['id', 'name', 'slug', 'description', 'role', 'created_at', 'updated_at']

    def get_role(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            membership = OrganizationMembership.objects.filter(organization=obj, user=request.user).first()
            return membership.role if membership else None
        return None

class OrganizationMembershipSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = OrganizationMembership
        fields = ['id', 'organization', 'user', 'role', 'joined_at']

class OrganizationInvitationSerializer(serializers.ModelSerializer):
    invited_by_username = serializers.ReadOnlyField(source='invited_by.username')
    organization_name = serializers.ReadOnlyField(source='organization.name')
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = OrganizationInvitation
        fields = [
            'id', 'organization', 'organization_name', 'email', 'role',
            'invited_by_username', 'token', 'expires_at', 'is_accepted',
            'is_expired', 'created_at'
        ]


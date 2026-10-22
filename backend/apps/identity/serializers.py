from rest_framework import serializers
from django.contrib.auth.models import User
from .models import Organization, OrganizationMembership

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

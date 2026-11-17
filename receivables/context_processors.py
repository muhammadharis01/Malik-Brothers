def role_context(request):
    """
    Context processor to make user roles easily accessible in templates.
    """
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return {
            'is_admin': False,
            'is_receiving_clerk': False,
            'is_delivery_clerk': False,
            'is_accounts_clerk': False,
            'is_manager': False,
            'user_role_names': [],
            'current_user_role_label': 'Guest',
        }

    user = request.user
    is_admin = user.is_superuser or user.groups.filter(name='Admin').exists()
    is_receiving = user.groups.filter(name='Receiving Clerk').exists()
    is_delivery = user.groups.filter(name='Delivery Clerk').exists()
    is_accounts = user.groups.filter(name='Accounts Clerk').exists()
    is_manager = user.groups.filter(name='Manager').exists()

    roles = []
    if is_admin:
        roles.append('Admin')
    if is_manager:
        roles.append('Manager')
    if is_accounts:
        roles.append('Accounts Clerk')
    if is_delivery:
        roles.append('Delivery Clerk')
    if is_receiving:
        roles.append('Receiving Clerk')

    role_label = roles[0] if roles else ('Staff' if user.is_staff else 'User')

    return {
        'is_admin': is_admin,
        'is_receiving_clerk': is_receiving or is_admin,
        'is_delivery_clerk': is_delivery or is_admin,
        'is_accounts_clerk': is_accounts or is_admin,
        'is_manager': is_manager or is_admin,
        'user_role_names': roles,
        'current_user_role_label': role_label,
    }


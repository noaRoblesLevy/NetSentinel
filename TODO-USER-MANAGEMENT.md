# User Management Feature - Work In Progress

## Status: 90% Complete

## What's Done

### Backend (Complete)
- ✅ `backend/app/api/v1/endpoints/users.py` - Full CRUD API for user management
  - `GET /api/v1/users` - List all users (admin only)
  - `GET /api/v1/users/{id}` - Get user by ID (admin only)
  - `POST /api/v1/users` - Create new user (admin only)
  - `PATCH /api/v1/users/{id}` - Update user (admin only)
  - `DELETE /api/v1/users/{id}` - Delete user (admin only)
  - `POST /api/v1/users/{id}/reset-password` - Admin reset user password
- ✅ `backend/app/api/v1/router.py` - Users router included

### Frontend API Client (Complete)
- ✅ `frontend/src/lib/api.ts` - All API methods added:
  - `getUsers()`, `getUser()`, `createUser()`, `updateUser()`, `deleteUser()`, `adminResetPassword()`
- ✅ Types added: `UserWithDetails`, `CreateUserRequest`, `UpdateUserRequest`

### Frontend UI (Partially Complete)
- ✅ Settings.tsx updated with "Users" tab (only visible for admins)
- ✅ New imports added (Users, Plus, Pencil, Trash2, Loader2, KeyRound icons)
- ❌ `UserManagement` component NOT YET ADDED to Settings.tsx

## What Needs To Be Done

### Add UserManagement Component to Settings.tsx

The `UserManagement` component and its modal components need to be added at the end of `frontend/src/pages/Settings.tsx`.

The component should include:
1. **UserManagement** - Main component with:
   - Table showing all users (name, email, role, status, last login, actions)
   - "Add User" button
   - Action buttons: Edit, Reset Password, Toggle Active, Delete

2. **CreateUserModal** - Modal for creating new users with fields:
   - Full Name, Email, Password, Role (viewer/analyst/admin)

3. **EditUserModal** - Modal for editing existing users with fields:
   - Full Name, Email, Role

4. **ResetPasswordModal** - Modal for admin to reset a user's password

### Implementation Notes

- The Users tab is already conditionally rendered: `{user?.role === 'admin' && ...}`
- Use the existing UI components: Card, Button, Input, Select from shadcn/ui
- Use Lucide icons already imported
- Follow the same patterns as other components in Settings.tsx
- The API methods are ready in `api.ts`

### Testing

After completing the UI:
1. Login as admin user
2. Go to Settings → Users tab
3. Test: Create user, Edit user, Reset password, Deactivate/Activate, Delete user

## Files Modified (Uncommitted)

```
modified:   backend/app/api/v1/router.py
modified:   frontend/src/lib/api.ts
modified:   frontend/src/pages/Settings.tsx
new file:   backend/app/api/v1/endpoints/users.py
```

## Quick Start Command for Claude

When continuing on another machine, tell Claude:

```
Continue implementing the user management feature. Read TODO-USER-MANAGEMENT.md for context.
The backend API and frontend API client are complete.
You need to add the UserManagement component and its modals to Settings.tsx.
```

// MongoDB user creation script
// This script runs during container initialization

db = db.getSiblingDB('admin');

// Create root user
db.createUser({
  user: 'admin',
  pwd: 'password123',
  roles: [
    {
      role: 'userAdminAnyDatabase',
      db: 'admin'
    },
    {
      role: 'readWriteAnyDatabase',
      db: 'admin'
    }
  ]
});

// Switch to aistock_news database
db = db.getSiblingDB('aistock_news');

// Create application user for aistock_news database
db.createUser({
  user: 'admin',
  pwd: 'password123',
  roles: [
    {
      role: 'readWrite',
      db: 'aistock_news'
    }
  ]
});

print('MongoDB users created successfully');
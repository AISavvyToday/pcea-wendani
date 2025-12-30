# Generated manually to create transport tables if they don't exist

from django.db import migrations


def create_tables_if_not_exist(apps, schema_editor):
    """Create tables only if they don't exist"""
    db_alias = schema_editor.connection.alias
    
    with schema_editor.connection.cursor() as cursor:
        # Check if transport_routes table exists
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'transport_routes'
            );
        """)
        routes_exists = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_schema = 'public' 
                AND table_name = 'transport_fees'
            );
        """)
        fees_exists = cursor.fetchone()[0]
        
        # If tables don't exist, create them
        if not routes_exists:
            cursor.execute("""
                CREATE TABLE transport_routes (
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    id UUID NOT NULL PRIMARY KEY,
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    name VARCHAR(100) NOT NULL DEFAULT 'Route',
                    description TEXT NOT NULL,
                    pickup_points TEXT NOT NULL,
                    dropoff_points TEXT NOT NULL
                );
            """)
        
        if not fees_exists:
            # First ensure transport_routes exists (in case it was created above)
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = 'transport_routes'
                );
            """)
            if cursor.fetchone()[0]:
                cursor.execute("""
                    CREATE TABLE transport_fees (
                        created_at TIMESTAMP NOT NULL,
                        updated_at TIMESTAMP NOT NULL,
                        id UUID NOT NULL PRIMARY KEY,
                        is_active BOOLEAN NOT NULL DEFAULT TRUE,
                        term VARCHAR(10) NOT NULL,
                        amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
                        half_amount NUMERIC(10, 2),
                        academic_year_id UUID NOT NULL,
                        route_id UUID NOT NULL,
                        CONSTRAINT transport_fees_academic_year_id_fkey 
                            FOREIGN KEY (academic_year_id) REFERENCES academic_years(id) ON DELETE CASCADE,
                        CONSTRAINT transport_fees_route_id_fkey 
                            FOREIGN KEY (route_id) REFERENCES transport_routes(id) ON DELETE CASCADE,
                        CONSTRAINT transport_fees_route_id_academic_year_id_term_key 
                            UNIQUE (route_id, academic_year_id, term)
                    );
                """)


def reverse_func(apps, schema_editor):
    """Reverse migration - don't drop tables"""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('transport', '0001_initial'),
        ('academics', '0010_delete_transportroute'),
    ]

    operations = [
        migrations.RunPython(create_tables_if_not_exist, reverse_func),
    ]

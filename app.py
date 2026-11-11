
import streamlit as st
import sqlite3
import math
from datetime import datetime, date, timedelta

import pandas as pd
import folium
from streamlit_folium import st_folium


# ============================================================
# SUSTAINPLATE
# Real-Time Surplus Food Redistribution Prototype
# Simulated GPS + SustainBot + Pickup Tracking
# ============================================================

st.set_page_config(
    page_title="SustainPlate",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_NAME = "sustainplate.db"


# ============================================================
# DATABASE
# ============================================================

def get_connection():
    return sqlite3.connect(DB_NAME)


def init_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS donations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            restaurant TEXT NOT NULL,
            food_type TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            pickup_deadline TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            location_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available',
            matched_point TEXT,
            matched_distance REAL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donation_id INTEGER,
            recipient TEXT NOT NULL,
            message TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pickups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            donation_id INTEGER NOT NULL,
            volunteer TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def query_database(query, params=()):
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df


def execute_database(query, params=()):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(query, params)
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


# ============================================================
# DEMO GPS LOCATIONS
# ============================================================

RESTAURANTS = {
    "Green Leaf Restaurant": {
        "lat": 12.9716,
        "lon": 77.5946,
        "area": "Central Bengaluru"
    },
    "Campus Canteen": {
        "lat": 12.9352,
        "lon": 77.6245,
        "area": "South Bengaluru"
    },
    "Sunrise Food Court": {
        "lat": 12.9850,
        "lon": 77.6100,
        "area": "East Bengaluru"
    }
}


# These are DEMO community food-distribution points.
# They are not verified real-world shelters or slum locations.
COMMUNITY_POINTS = [
    {
        "name": "Community Food Point A",
        "lat": 12.9740,
        "lon": 77.6000,
        "area": "Demo Central Zone",
        "contact": "Demo coordinator",
        "status": "Accepting",
        "capacity": 100
    },
    {
        "name": "Community Food Point B",
        "lat": 12.9450,
        "lon": 77.6200,
        "area": "Demo South Zone",
        "contact": "Demo coordinator",
        "status": "Accepting",
        "capacity": 80
    },
    {
        "name": "Community Food Point C",
        "lat": 12.9900,
        "lon": 77.6300,
        "area": "Demo East Zone",
        "contact": "Demo coordinator",
        "status": "Accepting",
        "capacity": 60
    },
    {
        "name": "Community Food Point D",
        "lat": 12.9600,
        "lon": 77.5700,
        "area": "Demo West Zone",
        "contact": "Demo coordinator",
        "status": "Closed",
        "capacity": 0
    }
]


# ============================================================
# GPS DISTANCE CALCULATION
# ============================================================

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two GPS coordinates.
    Returns kilometers.
    """

    earth_radius = 6371.0

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)
    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1)
        * math.cos(lat2)
        * math.sin(dlon / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return earth_radius * c


def find_nearby_points(latitude, longitude):
    """
    Find accepting community food points
    and sort them by distance.
    """

    results = []

    for point in COMMUNITY_POINTS:

        distance = haversine_distance(
            latitude,
            longitude,
            point["lat"],
            point["lon"]
        )

        if point["status"] == "Accepting":

            item = point.copy()
            item["distance"] = round(distance, 2)

            results.append(item)

    results.sort(key=lambda x: x["distance"])

    return results


# ============================================================
# SESSION STATE
# ============================================================

def initialize_session():

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = [
            {
                "role": "assistant",
                "message": (
                    "Hello! I am SustainBot 🌱 "
                    "I can help you find nearby community food "
                    "points, notify partners and track pickups."
                )
            }
        ]

    if "selected_donation" not in st.session_state:
        st.session_state.selected_donation = None

    if "notification_sent" not in st.session_state:
        st.session_state.notification_sent = False


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def format_distance(distance):
    return f"{distance:.2f} km"


def get_donations():
    return query_database("""
        SELECT *
        FROM donations
        ORDER BY id DESC
    """)


def get_notifications():
    return query_database("""
        SELECT *
        FROM notifications
        ORDER BY id DESC
    """)


def get_pickups():
    return query_database("""
        SELECT *
        FROM pickups
        ORDER BY id DESC
    """)


def get_impact_metrics():

    donations = get_donations()

    if donations.empty:
        return {
            "meals": 0,
            "donations": 0,
            "completed": 0
        }

    completed = donations[
        donations["status"] == "Completed"
    ]

    return {
        "meals": int(completed["quantity"].sum()),
        "donations": len(donations),
        "completed": len(completed)
    }


def add_chat_message(role, message):

    st.session_state.chat_history.append({
        "role": role,
        "message": message
    })


# ============================================================
# SUSTAINBOT
# ============================================================

def chatbot_response(user_message):

    message = user_message.lower().strip()

    donations = get_donations()

    # Nearby location question
    if (
        "nearby" in message
        or "near" in message
        or "location" in message
        or "gps" in message
    ):

        restaurant = st.session_state.get(
            "restaurant_name",
            "Green Leaf Restaurant"
        )

        location = RESTAURANTS[restaurant]

        nearby = find_nearby_points(
            location["lat"],
            location["lon"]
        )

        if nearby:

            nearest = nearby[0]

            return (
                f"📍 The nearest accepting demo community point "
                f"is {nearest['name']}, "
                f"{nearest['distance']} km away. "
                f"Area: {nearest['area']}. "
                f"Would you like to notify this partner?"
            )

        return "No accepting demo community points found."

    # Donation status
    if (
        "donation" in message
        or "food" in message
        or "surplus" in message
    ):

        if donations.empty:
            return (
                "You have no donations yet. "
                "Go to Add Surplus Food and create one."
            )

        latest = donations.iloc[0]

        return (
            f"Your latest donation is "
            f"{latest['quantity']} meals of "
            f"{latest['food_type']}. "
            f"Current status: {latest['status']}."
        )

    # Notification
    if (
        "notify" in message
        or "notification" in message
        or "alert" in message
    ):

        return (
            "You can notify the nearest accepting demo "
            "community point from the Notifications tab."
        )

    # Pickup
    if (
        "pickup" in message
        or "collect" in message
        or "volunteer" in message
    ):

        return (
            "Pickup tracking is available in the "
            "Pickup Tracking tab. "
            "Select a donation and assign a demo volunteer."
        )

    # Impact
    if (
        "impact" in message
        or "meals" in message
        or "waste" in message
    ):

        metrics = get_impact_metrics()

        return (
            f"SustainPlate has recorded "
            f"{metrics['meals']} completed meals redistributed "
            f"and {metrics['completed']} completed donations."
        )

    # Help
    if (
        "help" in message
        or "hello" in message
        or "hi" in message
    ):

        return (
            "I can help with:\n\n"
            "• Nearby community points\n"
            "• Surplus food details\n"
            "• Notifications\n"
            "• Pickup tracking\n"
            "• Community impact"
        )

    return (
        "I can help you find nearby community food points, "
        "check donations, send notifications and track pickups. "
        "Try asking: 'Find nearby points'."
    )


# ============================================================
# SIDEBAR
# ============================================================

def render_sidebar():

    st.sidebar.title("🌱 SustainPlate")

    st.sidebar.caption(
        "Surplus Food Redistribution Platform"
    )

    st.sidebar.divider()

    st.sidebar.subheader("Demo Restaurant")

    restaurant_name = st.sidebar.selectbox(
        "Select restaurant",
        list(RESTAURANTS.keys())
    )

    st.session_state.restaurant_name = restaurant_name

    location = RESTAURANTS[restaurant_name]

    st.sidebar.info(
        f"📍 {location['area']}\n\n"
        f"Latitude: {location['lat']}\n\n"
        f"Longitude: {location['lon']}"
    )

    st.sidebar.divider()

    st.sidebar.caption(
        "GPS Mode: Simulated Demo GPS"
    )

    st.sidebar.caption(
        "Community points are fictional demo data."
    )


# ============================================================
# DASHBOARD
# ============================================================

def render_dashboard():

    st.header("📊 Restaurant Dashboard")

    st.write(
        "Monitor surplus food, redistribution and community impact."
    )

    metrics = get_impact_metrics()
    donations = get_donations()

    total_meals = (
        int(donations["quantity"].sum())
        if not donations.empty else 0
    )

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Total Donations",
        metrics["donations"]
    )

    col2.metric(
        "Meals Listed",
        total_meals
    )

    col3.metric(
        "Meals Redistributed",
        metrics["meals"]
    )

    col4.metric(
        "Completed Pickups",
        metrics["completed"]
    )

    st.divider()

    st.subheader("Recent Donations")

    if donations.empty:

        st.info(
            "No donations yet. Add surplus food to begin."
        )

    else:

        display_columns = [
            "id",
            "restaurant",
            "food_type",
            "quantity",
            "pickup_deadline",
            "status",
            "matched_point"
        ]

        st.dataframe(
            donations[display_columns],
            use_container_width=True,
            hide_index=True
        )

    st.divider()

    st.subheader("Community Impact")

    st.write(
        "Every completed donation contributes to reducing "
        "food waste and supporting community food access."
    )

    if metrics["meals"] > 0:

        st.success(
            f"🎉 {metrics['meals']} meals redistributed "
            "through completed demo pickups!"
        )

    else:

        st.info(
            "Complete a pickup to see community impact."
        )


# ============================================================
# ADD SURPLUS FOOD
# ============================================================

def render_surplus_form():

    st.header("🍱 Add Surplus Food")

    st.write(
        "Enter surplus food details from your restaurant."
    )

    restaurant_name = st.session_state.restaurant_name
    restaurant_location = RESTAURANTS[restaurant_name]

    with st.form("surplus_form"):

        food_type = st.selectbox(
            "Food Type",
            [
                "Vegetarian Rice Meals",
                "Chapati and Curry",
                "Bread and Bakery Items",
                "Packed Lunches",
                "Fruits and Vegetables",
                "Other"
            ]
        )

        quantity = st.number_input(
            "Number of Meal Portions",
            min_value=1,
            max_value=10000,
            value=20,
            step=1
        )

        deadline = st.date_input(
            "Pickup Date",
            value=date.today()
        )

        pickup_time = st.time_input(
            "Pickup Deadline"
        )

        notes = st.text_area(
            "Food Notes",
            placeholder=(
                "Example: Fresh vegetarian rice meals, "
                "packed and ready for pickup."
            )
        )

        submit = st.form_submit_button(
            "➕ Add Surplus Donation",
            use_container_width=True
        )

    if submit:

        pickup_deadline = (
            f"{deadline} {pickup_time}"
        )

        donation_id = execute_database(
            """
            INSERT INTO donations
            (
                restaurant,
                food_type,
                quantity,
                pickup_deadline,
                latitude,
                longitude,
                location_name,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                restaurant_name,
                food_type,
                int(quantity),
                pickup_deadline,
                restaurant_location["lat"],
                restaurant_location["lon"],
                restaurant_location["area"],
                "Available",
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
        )

        st.session_state.selected_donation = donation_id

        st.success(
            f"Donation #{donation_id} created successfully!"
        )

        st.info(
            "Next step: Open Nearby Matching to find "
            "a community food point."
        )


# ============================================================
# NEARBY MATCHING
# ============================================================

def render_nearby_matching():

    st.header("📍 Nearby Community Matching")

    st.write(
        "Find the nearest accepting demo community food points "
        "using simulated GPS."
    )

    restaurant_name = st.session_state.restaurant_name

    location = RESTAURANTS[restaurant_name]

    st.info(
        f"Restaurant: {restaurant_name}\n\n"
        f"Area: {location['area']}\n\n"
        f"GPS: {location['lat']}, {location['lon']}"
    )

    nearby = find_nearby_points(
        location["lat"],
        location["lon"]
    )

    if not nearby:

        st.warning(
            "No accepting community food points found."
        )

        return

    st.subheader("Nearest Verified Demo Points")

    st.caption(
        "Demo points are fictional. Real deployment "
        "requires verified partner organizations."
    )

    for index, point in enumerate(nearby):

        with st.container(border=True):

            col1, col2, col3 = st.columns([3, 2, 1])

            col1.subheader(point["name"])

            col1.write(
                f"Area: {point['area']}\n\n"
                f"Contact: {point['contact']}"
            )

            col2.metric(
                "Distance",
                format_distance(point["distance"])
            )

            col2.write(
                f"Capacity: {point['capacity']} meals"
            )

            if col3.button(
                "Select",
                key=f"select_point_{index}"
            ):

                st.session_state.selected_point = point

                st.success(
                    f"Selected {point['name']}"
                )

    st.divider()

    st.subheader("Map View")

    map_object = folium.Map(
        location=[
            location["lat"],
            location["lon"]
        ],
        zoom_start=13
    )

    folium.Marker(
        [
            location["lat"],
            location["lon"]
        ],
        tooltip="Restaurant",
        popup=restaurant_name,
        icon=folium.Icon(
            color="blue",
            icon="cutlery",
            prefix="fa"
        )
    ).add_to(map_object)

    for point in nearby:

        folium.Marker(
            [
                point["lat"],
                point["lon"]
            ],
            tooltip=point["name"],
            popup=(
                f"{point['name']}<br>"
                f"Distance: {point['distance']} km"
            ),
            icon=folium.Icon(
                color="green",
                icon="heart",
                prefix="fa"
            )
        ).add_to(map_object)

    st_folium(
        map_object,
        width=None,
        height=450
    )

    st.divider()

    if "selected_point" in st.session_state:

        point = st.session_state.selected_point

        st.success(
            f"Selected point: {point['name']} "
            f"({point['distance']} km away)"
        )

        donations = get_donations()

        if donations.empty:

            st.warning(
                "Please add a surplus donation first."
            )

        else:

            available = donations[
                donations["status"] == "Available"
            ]

            if available.empty:

                st.info(
                    "No available donations to match."
                )

            else:

                donation_id = st.selectbox(
                    "Select donation",
                    available["id"].tolist()
                )

                if st.button(
                    "🤝 Match Donation to This Point",
                    use_container_width=True
                ):

                    execute_database(
                        """
                        UPDATE donations
                        SET
                            matched_point = ?,
                            matched_distance = ?,
                            status = 'Matched'
                        WHERE id = ?
                        """,
                        (
                            point["name"],
                            point["distance"],
                            int(donation_id)
                        )
                    )

                    st.session_state.selected_donation = int(
                        donation_id
                    )

                    st.success(
                        "Donation matched successfully!"
                    )

                    st.info(
                        "Open Notifications to alert "
                        "the community partner."
                    )


# ============================================================
# NOTIFICATIONS
# ============================================================

def render_notifications():

    st.header("🔔 Notifications")

    st.write(
        "Send a simulated notification to the matched "
        "community food point."
    )

    donations = get_donations()

    if donations.empty:

        st.info(
            "No donations available."
        )

        return

    matched = donations[
        donations["status"].isin(
            ["Matched", "Notified"]
        )
    ]

    if matched.empty:

        st.info(
            "No matched donations yet. "
            "Use Nearby Matching first."
        )

        return

    donation_id = st.selectbox(
        "Select matched donation",
        matched["id"].tolist()
    )

    donation = matched[
        matched["id"] == donation_id
    ].iloc[0]

    st.subheader(
        f"Donation #{donation_id}"
    )

    st.write(
        f"Food: {donation['food_type']}\n\n"
        f"Quantity: {donation['quantity']} meals\n\n"
        f"Pickup Deadline: {donation['pickup_deadline']}\n\n"
        f"Community Point: {donation['matched_point']}"
    )

    message = (
        f"🌱 SustainPlate Alert\n\n"
        f"Surplus food available!\n\n"
        f"Food: {donation['food_type']}\n"
        f"Quantity: {donation['quantity']} meals\n"
        f"Restaurant: {donation['restaurant']}\n"
        f"Pickup Deadline: {donation['pickup_deadline']}\n\n"
        f"Please confirm pickup through SustainPlate."
    )

    st.text_area(
        "Notification Preview",
        value=message,
        height=220,
        disabled=True
    )

    if st.button(
        "📢 Send Simulated Notification",
        use_container_width=True
    ):

        execute_database(
            """
            INSERT INTO notifications
            (
                donation_id,
                recipient,
                message,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(donation_id),
                donation["matched_point"],
                message,
                "Sent",
                datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            )
        )

        execute_database(
            """
            UPDATE donations
            SET status = 'Notified'
            WHERE id = ?
            """,
            (int(donation_id),)
        )

        st.success(
            "✅ Simulated notification sent!"
        )

        st.info(
            "In a real system, this could connect "
            "to WhatsApp, SMS or email."
        )

    st.divider()

    st.subheader("Notification History")

    notifications = get_notifications()

    if notifications.empty:

        st.info("No notifications sent yet.")

    else:

        st.dataframe(
            notifications,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# PICKUP TRACKING
# ============================================================

def render_pickup_tracking():

    st.header("🚚 Pickup Tracking")

    st.write(
        "Track the collection of surplus food donations."
    )

    donations = get_donations()

    if donations.empty:

        st.info(
            "No donations available."
        )

        return

    trackable = donations[
        donations["status"].isin(
            ["Notified", "Assigned", "Collected"]
        )
    ]

    if trackable.empty:

        st.info(
            "No donations ready for pickup tracking."
        )

        return

    donation_id = st.selectbox(
        "Select donation",
        trackable["id"].tolist()
    )

    donation = trackable[
        trackable["id"] == donation_id
    ].iloc[0]

    st.subheader(
        f"Donation #{donation_id}"
    )

    st.write(
        f"Food: {donation['food_type']}\n\n"
        f"Quantity: {donation['quantity']} meals\n\n"
        f"Destination: {donation['matched_point']}\n\n"
        f"Current Status: {donation['status']}"
    )

    volunteer = st.text_input(
        "Demo Volunteer Name",
        value="Volunteer A"
    )

    col1, col2 = st.columns(2)

    with col1:

        if st.button(
            "👤 Assign Volunteer",
            use_container_width=True
        ):

            execute_database(
                """
                INSERT INTO pickups
                (
                    donation_id,
                    volunteer,
                    status,
                    created_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    int(donation_id),
                    volunteer,
                    "Assigned",
                    datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )
            )

            execute_database(
                """
                UPDATE donations
                SET status = 'Assigned'
                WHERE id = ?
                """,
                (int(donation_id),)
            )

            st.success(
                f"Volunteer {volunteer} assigned!"
            )

    with col2:

        if st.button(
            "📦 Mark Food Collected",
            use_container_width=True
        ):

            execute_database(
                """
                UPDATE donations
                SET status = 'Collected'
                WHERE id = ?
                """,
                (int(donation_id),)
            )

            execute_database(
                """
                UPDATE pickups
                SET status = 'Collected'
                WHERE donation_id = ?
                AND status = 'Assigned'
                """,
                (int(donation_id),)
            )

            st.success(
                "Food marked as collected!"
            )

    if st.button(
        "✅ Complete Pickup",
        use_container_width=True
    ):

        execute_database(
            """
            UPDATE donations
            SET status = 'Completed'
            WHERE id = ?
            """,
            (int(donation_id),)
        )

        execute_database(
            """
            UPDATE pickups
            SET status = 'Completed'
            WHERE donation_id = ?
            """,
            (int(donation_id),)
        )

        st.success(
            "🎉 Pickup completed successfully!"
        )

        st.balloons()

    st.divider()

    st.subheader("Pickup History")

    pickups = get_pickups()

    if pickups.empty:

        st.info("No pickup records yet.")

    else:

        st.dataframe(
            pickups,
            use_container_width=True,
            hide_index=True
        )


# ============================================================
# SUSTAINBOT UI
# ============================================================

def render_chatbot():

    st.header("🤖 SustainBot")

    st.write(
        "Your AI-style assistant for surplus food redistribution."
    )

    st.info(
        "This prototype uses a local rule-based chatbot. "
        "It does not require an external AI API."
    )

    for item in st.session_state.chat_history:

        if item["role"] == "user":

            with st.chat_message("user"):
                st.write(item["message"])

        else:

            with st.chat_message("assistant"):
                st.write(item["message"])

    user_message = st.chat_input(
        "Ask SustainBot..."
    )

    if user_message:

        add_chat_message(
            "user",
            user_message
        )

        response = chatbot_response(
            user_message
        )

        add_chat_message(
            "assistant",
            response
        )

        st.rerun()


# ============================================================
# DEMO RESET
# ============================================================

def render_reset():

    st.sidebar.divider()

    st.sidebar.subheader("Demo Controls")

    if st.sidebar.button(
        "🗑️ Reset Demo Data",
        use_container_width=True
    ):

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("DELETE FROM donations")
        cursor.execute("DELETE FROM notifications")
        cursor.execute("DELETE FROM pickups")

        conn.commit()
        conn.close()

        st.session_state.chat_history = [
            {
                "role": "assistant",
                "message": (
                    "Demo reset complete! "
                    "How can I help you?"
                )
            }
        ]

        st.sidebar.success(
            "Demo data reset."
        )

        st.rerun()


# ============================================================
# MAIN APP
# ============================================================

init_database()
initialize_session()
render_sidebar()
render_reset()

st.title("🌱 SustainPlate")
st.caption(
    "Real-Time Surplus Food Redistribution "
    "and Local Community Impact Platform"
)

st.write(
    "Connect surplus food from restaurants "
    "with verified community food partners."
)

st.divider()

tabs = st.tabs([
    "📊 Dashboard",
    "🍱 Add Surplus",
    "📍 Nearby Matching",
    "🔔 Notifications",
    "🚚 Pickup Tracking",
    "🤖 SustainBot"
])

with tabs[0]:
    render_dashboard()

with tabs[1]:
    render_surplus_form()

with tabs[2]:
    render_nearby_matching()

with tabs[3]:
    render_notifications()

with tabs[4]:
    render_pickup_tracking()

with tabs[5]:
    render_chatbot()
"""SAMPLE DATA for local development and demos.

Every company, founder, investor and amount below is fictional and exists only
to exercise the UI. Never run this against a production database (the
`flask seed` command refuses to).
"""
import os
import random
from datetime import date, timedelta

from sqlalchemy import select

from extensions import db
from models import (BiddingRules, Category, Founder, FundingProfile, GalleryImage, InvestorProfile, Payment,
                    PlatformSetting, Product, RankingEvent, Startup, StartupMember, StartupUpdate, StartupView,
                    User, utcnow)
from models.bid import BID_ACTIVE, BID_CANCELLED, BID_FAILED, BID_SUPERSEDED, Bid
from models.payment import PAY_CANCELLED, PAY_FAILED, PAY_PAID
from services import ranking_service

CRORE = 1_00_00_000
LAKH = 1_00_000

DEMO_ACCOUNTS = [
    ("admin@deeptechindia.local", "Admin@12345", "Platform Admin", "admin"),
    ("founder@deeptechindia.local", "Founder@12345", "Arjun Mehta", "startup_owner"),
    ("investor@deeptechindia.local", "Investor@12345", "Kavya Raman", "investor"),
]

CATEGORIES = [
    ("SpaceTech", "spacetech", "rocket", "#5b3df5", "Launch vehicles, satellites and in-space services."),
    ("Robotics", "robotics", "bot", "#7c3aed", "Industrial automation, cobots and autonomous systems."),
    ("Artificial Intelligence", "ai", "sparkles", "#2563eb", "Foundation models, computer vision and applied AI."),
    ("Biotech", "biotech", "dna", "#059669", "Biologics, cell therapy and synthetic biology."),
    ("Semiconductors", "semiconductors", "cpu", "#0891b2", "Chip design, fabs, packaging and EDA."),
    ("ClimateTech", "climatetech", "leaf", "#16a34a", "Carbon capture, climate analytics and adaptation."),
    ("Clean Energy", "clean-energy", "zap", "#f59e0b", "Storage, green hydrogen and renewables."),
    ("AgriTech", "agritech", "sprout", "#65a30d", "Precision farming, crop science and agri-sensing."),
    ("Quantum", "quantum", "atom", "#9333ea", "Quantum computing, sensing and secure communication."),
    ("MedTech", "medtech", "heart", "#e11d48", "Medical devices and point-of-care diagnostics."),
    ("Defence & Aerospace", "defence", "shield", "#475569", "Radar, avionics and strategic technologies."),
    ("EV & Mobility", "ev-mobility", "car", "#0ea5e9", "Batteries, powertrains and charging."),
    ("Advanced Materials", "advanced-materials", "hexagon", "#b45309", "Graphene, composites and nanomaterials."),
    ("IoT & Sensors", "iot", "radar", "#0d9488", "Industrial IoT, sensing and edge devices."),
    ("Drones & UAVs", "drones", "drone", "#4f46e5", "Unmanned aerial systems for industry and agriculture."),
]

# (name, category, city, state, founded, team, tags, tagline, description,
#  stage, raised_inr, raising, target_inr, verified, founders, products)
STARTUPS = [
    ("Akashdeep Aerospace", "spacetech", "Hyderabad", "Telangana", 2018, "201-500",
     "Launch Vehicles, Deep-Tech, Propulsion",
     "Making space accessible for a billion dreams.",
     "Akashdeep Aerospace is building next-generation small-satellite launch vehicles that make space access "
     "affordable and reliable. Its 3D-printed cryogenic engines and modular stages let customers book a "
     "dedicated ride to orbit in weeks rather than years, serving businesses, researchers and governments.",
     "Series B", 990 * CRORE // 10, True, 400 * CRORE, True,
     [("Rohan Iyer", "Co-founder & CEO"), ("Meera Kulkarni", "Co-founder & COO"), ("Sandeep Rao", "Co-founder & CTO")],
     [("Vikram-class Launch Vehicle", "Three-stage solid and cryogenic launcher for 300 kg to SSO."),
      ("Rideshare Services", "Shared launch slots for cubesats and microsats."),
      ("Orbital Transfer Stage", "Kick stage for precise multi-orbit deployment.")]),
    ("Neelgagan Satellites", "spacetech", "Bengaluru", "Karnataka", 2019, "51-200",
     "Earth Observation, Hyperspectral, Satellites",
     "Hyperspectral eyes in orbit for a sustainable planet.",
     "Neelgagan designs and operates a constellation of hyperspectral imaging satellites that detect crop "
     "stress, methane leaks and water quality from orbit. Its analytics platform turns raw imagery into "
     "decision-ready insights for agriculture, mining and environmental agencies.",
     "Series A", 300 * CRORE, True, 250 * CRORE, True,
     [("Ananya Bose", "Founder & CEO"), ("Vivek Natarajan", "Co-founder & CTO")],
     [("Neel-1 Hyperspectral Satellite", "150-band imager at 5 m resolution."),
      ("Gagan Insights", "SaaS analytics on top of satellite data.")]),
    ("Vyomika Space Labs", "spacetech", "Chennai", "Tamil Nadu", 2021, "11-50",
     "In-Space Propulsion, Green Propellants",
     "Clean, efficient propulsion for the new space economy.",
     "Vyomika Space Labs develops non-toxic green-propellant thrusters and electric propulsion modules for "
     "small satellites, cutting integration time and handling risk for satellite builders worldwide.",
     "Seed", 18 * CRORE, True, 60 * CRORE, False,
     [("Lakshmi Sundaram", "Founder & CEO"), ("Imran Qureshi", "Head of Propulsion")],
     [("VG-10 Green Thruster", "1 N thruster with a non-toxic monopropellant."),
      ("Hall-Effect Module", "Electric propulsion for orbit raising.")]),
    ("Garuda Robotics", "robotics", "Bengaluru", "Karnataka", 2017, "51-200",
     "Autonomous Systems, Industrial Inspection",
     "Autonomous robots for industrial and defence applications.",
     "Garuda Robotics builds autonomous ground and aerial robots that inspect pipelines, power lines and "
     "large industrial plants. Its perception stack works in GPS-denied environments and harsh weather.",
     "Series A", 120 * CRORE, True, 150 * CRORE, True,
     [("Karthik Menon", "Founder & CEO"), ("Priya Deshmukh", "VP Engineering")],
     [("Garuda Crawler", "Pipeline inspection robot with ultrasonic sensing."),
      ("SkyScout", "Autonomous inspection drone for power infrastructure.")]),
    ("Yantrik Automation", "robotics", "Pune", "Maharashtra", 2020, "11-50",
     "Cobots, Manufacturing, Machine Vision",
     "Affordable collaborative robots for Indian MSMEs.",
     "Yantrik Automation designs low-cost collaborative robot arms with no-code programming so that small "
     "manufacturers can automate welding, packaging and machine tending without specialist engineers.",
     "Pre-Series A", 22 * CRORE, True, 45 * CRORE, False,
     [("Siddharth Joshi", "Founder & CEO"), ("Neha Patil", "Co-founder & CTO")],
     [("Yantra-6 Cobot", "6-axis collaborative arm, 5 kg payload."),
      ("FlowStudio", "No-code robot programming software.")]),
    ("BharatAI", "ai", "Pune", "Maharashtra", 2022, "51-200",
     "LLMs, Indic Languages, Speech",
     "Foundation models built for India's languages.",
     "BharatAI trains large language and speech models for 22 Indian languages, powering customer support, "
     "government services and education for the next billion users with low-latency, on-premise options.",
     "Series A", 210 * CRORE, True, 400 * CRORE, True,
     [("Aditya Kulkarni", "Founder & CEO"), ("Fatima Sheikh", "Chief Scientist"), ("Rahul Verma", "CTO")],
     [("Sutra LLM", "Multilingual foundation model family."),
      ("Vaani Speech", "Speech recognition and synthesis for Indic languages.")]),
    ("Nayan Vision", "ai", "Gurugram", "Haryana", 2019, "11-50",
     "Computer Vision, Quality Control",
     "Computer vision that never blinks on the factory floor.",
     "Nayan Vision deploys edge AI cameras that catch manufacturing defects in real time, reducing scrap and "
     "recalls for automotive, electronics and pharmaceutical manufacturers.",
     "Seed", 14 * CRORE, False, 0, True,
     [("Ishaan Kapoor", "Founder & CEO"), ("Ritu Saxena", "Head of AI")],
     [("Nayan Edge", "Inspection camera with on-device AI."),
      ("DefectNet", "Self-learning defect detection platform.")]),
    ("BioSage", "biotech", "Delhi", "Delhi", 2018, "51-200",
     "Biologics, Rare Diseases, AI Drug Discovery",
     "Novel biologics for rare diseases using AI-driven research.",
     "BioSage combines machine learning with wet-lab automation to discover antibodies and enzyme therapies "
     "for rare genetic disorders, with two candidates entering pre-clinical studies.",
     "Series A", 160 * CRORE, True, 300 * CRORE, True,
     [("Dr. Sunita Rao", "Founder & CEO"), ("Dr. Manish Gupta", "Chief Scientific Officer")],
     [("SageDiscover", "AI platform for antibody design."),
      ("BSG-101", "Enzyme replacement therapy candidate.")]),
    ("Sanjeevani Cell Therapies", "biotech", "Bengaluru", "Karnataka", 2020, "11-50",
     "CAR-T, Cell Therapy, Oncology",
     "Affordable cell therapies engineered in India.",
     "Sanjeevani develops CAR-T cell therapies manufactured at a fraction of global cost, bringing curative "
     "cancer treatments within reach of Indian patients and hospitals.",
     "Seed", 35 * CRORE, True, 120 * CRORE, False,
     [("Dr. Arvind Pillai", "Founder & CEO"), ("Dr. Shalini Reddy", "Head of Clinical")],
     [("SCT-19", "CD19-targeted CAR-T candidate."),
      ("CellForge", "Automated closed-system manufacturing.")]),
    ("IndicSemi", "semiconductors", "Noida", "Uttar Pradesh", 2019, "51-200",
     "Chip Design, Low Power, RISC-V",
     "High-performance, low-power chips designed in India.",
     "IndicSemi designs ultra-low-power system-on-chips for wearables, smart meters and edge AI devices, "
     "with a growing portfolio of silicon-proven IP blocks.",
     "Series A", 140 * CRORE, True, 200 * CRORE, True,
     [("Vikram Sharma", "Founder & CEO"), ("Deepa Krishnan", "VP Silicon")],
     [("Shakti-M SoC", "RISC-V microcontroller with AI accelerator."),
      ("IndicIP Library", "Licensable analog and mixed-signal IP.")]),
    ("Silicon Sutra", "semiconductors", "Bengaluru", "Karnataka", 2021, "11-50",
     "EDA, Verification, AI for Chips",
     "AI-native tools that verify chips in days, not months.",
     "Silicon Sutra builds AI-assisted verification software that automatically generates test benches and "
     "finds corner-case bugs, shortening tape-out cycles for chip design teams.",
     "Seed", 16 * CRORE, True, 50 * CRORE, False,
     [("Harsha Vardhan", "Founder & CEO"), ("Pooja Nair", "Co-founder")],
     [("SutraVerify", "AI test-bench generator."),
      ("Coverage Copilot", "Coverage closure assistant.")]),
    ("Jalvayu Carbon", "climatetech", "Mumbai", "Maharashtra", 2021, "11-50",
     "Carbon Capture, DAC, Net Zero",
     "Pulling carbon from the air at Indian costs.",
     "Jalvayu Carbon develops solid-sorbent direct-air-capture modules powered by waste heat, producing "
     "verifiable carbon removal credits for corporates committed to net zero.",
     "Pre-Series A", 28 * CRORE, True, 80 * CRORE, True,
     [("Nikhil Sawant", "Founder & CEO"), ("Ayesha Khan", "Head of R&D")],
     [("JV-100 Capture Module", "Containerised direct-air-capture unit."),
      ("CarbonLedger", "MRV platform for removal credits.")]),
    ("Prithvi Climate Analytics", "climatetech", "Ahmedabad", "Gujarat", 2020, "11-50",
     "Climate Risk, Geospatial AI",
     "Hyper-local climate risk intelligence for lenders and insurers.",
     "Prithvi combines satellite data and climate models to score flood, heat and drought risk at the level "
     "of a single farm or factory, helping banks and insurers price climate risk.",
     "Seed", 12 * CRORE, False, 0, False,
     [("Gaurav Desai", "Founder & CEO"), ("Sneha Shah", "Chief Data Scientist")],
     [("RiskScope", "Asset-level climate risk API."),
      ("FloodSense", "Flood forecasting for urban districts.")]),
    ("UrjaNext", "clean-energy", "Ahmedabad", "Gujarat", 2018, "51-200",
     "Energy Storage, Grid, Batteries",
     "Advanced energy storage for a sustainable future.",
     "UrjaNext manufactures grid-scale battery energy storage systems with proprietary thermal management, "
     "helping utilities and solar parks firm up renewable power.",
     "Series B", 450 * CRORE, True, 500 * CRORE, True,
     [("Rajesh Patel", "Founder & CEO"), ("Kiran Mehta", "CTO")],
     [("UrjaStack", "Containerised 2 MWh storage system."),
      ("GridBrain", "Energy management software.")]),
    ("Suryansh Hydrogen", "clean-energy", "Jaipur", "Rajasthan", 2021, "11-50",
     "Green Hydrogen, Electrolysers",
     "Low-cost electrolysers for India's green hydrogen mission.",
     "Suryansh Hydrogen develops AEM electrolysers free of precious metals, designed to run directly on "
     "variable solar power in desert conditions.",
     "Seed", 20 * CRORE, True, 75 * CRORE, False,
     [("Abhishek Rathore", "Founder & CEO"), ("Dr. Nidhi Agarwal", "Chief Technologist")],
     [("SH-250 Electrolyser", "250 kW AEM electrolyser stack."),
      ("H2 Insight", "Plant monitoring software.")]),
    ("KrishiSense", "agritech", "Indore", "Madhya Pradesh", 2019, "51-200",
     "Soil Sensing, Precision Farming",
     "Soil sensors and AI advisory for 1 million farmers.",
     "KrishiSense deploys low-cost soil probes and satellite analytics to give smallholder farmers precise "
     "irrigation and fertiliser advice in their own language, raising yields while saving water.",
     "Series A", 85 * CRORE, False, 0, True,
     [("Manoj Chouhan", "Founder & CEO"), ("Swati Jain", "Head of Agronomy")],
     [("SoilPulse Probe", "Solar-powered soil moisture and NPK sensor."),
      ("Krishi Mitra App", "Vernacular farm advisory app.")]),
    ("Ankur Genomics", "agritech", "Hyderabad", "Telangana", 2020, "11-50",
     "Crop Genomics, Gene Editing",
     "Climate-resilient seeds through precision breeding.",
     "Ankur Genomics uses genomic selection and gene editing to develop drought- and heat-tolerant varieties "
     "of rice, millets and pulses for India's changing climate.",
     "Pre-Series A", 30 * CRORE, True, 90 * CRORE, False,
     [("Dr. Venkatesh Reddy", "Founder & CEO"), ("Dr. Farah Ali", "Head of Breeding")],
     [("AnkurSelect", "Genomic selection platform."),
      ("HeatShield Rice", "Heat-tolerant rice line in field trials.")]),
    ("Tarang Quantum", "quantum", "Bengaluru", "Karnataka", 2021, "11-50",
     "QKD, Quantum Security, Photonics",
     "Quantum-safe communication for critical infrastructure.",
     "Tarang Quantum builds quantum key distribution systems and post-quantum cryptography gateways that "
     "protect banking, defence and telecom networks against future quantum attacks.",
     "Seed", 25 * CRORE, True, 100 * CRORE, True,
     [("Dr. Anirudh Sen", "Founder & CEO"), ("Kriti Malhotra", "Head of Product")],
     [("TQ-Link QKD", "Fibre-based quantum key distribution."),
      ("PQC Gateway", "Post-quantum VPN appliance.")]),
    ("Prana Diagnostics", "medtech", "Chennai", "Tamil Nadu", 2018, "51-200",
     "Point-of-Care, Diagnostics, Microfluidics",
     "Lab-quality diagnostics at the point of care.",
     "Prana Diagnostics makes battery-powered microfluidic analysers that run 30+ blood tests in 15 minutes, "
     "bringing lab-grade diagnostics to primary health centres.",
     "Series A", 95 * CRORE, True, 150 * CRORE, True,
     [("Dr. Kavitha Subramanian", "Founder & CEO"), ("Arun Prakash", "CTO")],
     [("Prana Lab-in-a-Box", "Portable blood analyser."),
      ("PranaCloud", "Remote reporting for clinics.")]),
    ("Hridaya Devices", "medtech", "Kochi", "Kerala", 2020, "11-50",
     "Cardiac Monitoring, Wearables",
     "Wearable cardiac monitors for every district hospital.",
     "Hridaya Devices builds patch-based ECG monitors with AI arrhythmia detection, enabling continuous "
     "cardiac care outside large city hospitals.",
     "Seed", 11 * CRORE, True, 40 * CRORE, False,
     [("Dr. Thomas Varghese", "Founder & CEO"), ("Anjali Menon", "Head of Engineering")],
     [("HridayPatch", "7-day wearable ECG patch."),
      ("RhythmAI", "Arrhythmia detection software.")]),
    ("Vajra Defence Systems", "defence", "Hyderabad", "Telangana", 2017, "201-500",
     "Radar, Counter-Drone, Electronic Warfare",
     "Indigenous radar and counter-drone systems.",
     "Vajra Defence Systems designs AESA radars and integrated counter-drone solutions for armed forces and "
     "critical infrastructure protection, built on fully indigenous technology.",
     "Series B", 380 * CRORE, False, 0, True,
     [("Col. (Retd.) Prakash Nair", "Founder & CEO"), ("Shruti Agarwal", "CTO")],
     [("Vajra-R AESA Radar", "Compact multi-mission radar."),
      ("DroneShield-V", "Detect, track and neutralise system.")]),
    ("Chakra EV Powertrains", "ev-mobility", "Chennai", "Tamil Nadu", 2019, "51-200",
     "Motors, Controllers, Two-Wheelers",
     "Rare-earth-free motors for India's electric vehicles.",
     "Chakra EV Powertrains designs magnet-free switched reluctance motors and controllers that reduce cost "
     "and supply-chain risk for electric two- and three-wheelers.",
     "Series A", 110 * CRORE, True, 180 * CRORE, True,
     [("Vignesh Raman", "Founder & CEO"), ("Divya Iyer", "VP Engineering")],
     [("ChakraDrive SR-5", "5 kW rare-earth-free motor."),
      ("Chakra MCU", "Integrated motor controller.")]),
    ("Vidyut Cells", "ev-mobility", "Pune", "Maharashtra", 2021, "11-50",
     "Sodium-ion, Batteries, Energy Storage",
     "Sodium-ion batteries made from abundant Indian materials.",
     "Vidyut Cells develops sodium-ion battery chemistry and cells for two-wheelers and stationary storage, "
     "eliminating dependence on imported lithium and cobalt.",
     "Pre-Series A", 40 * CRORE, True, 120 * CRORE, False,
     [("Omkar Bhosale", "Founder & CEO"), ("Dr. Pallavi Kale", "Chief Scientist")],
     [("VC-Na18650 Cell", "Sodium-ion cylindrical cell."),
      ("Vidyut Pack", "Swappable battery pack.")]),
    ("Dhatu Materials", "advanced-materials", "Bengaluru", "Karnataka", 2018, "11-50",
     "Graphene, Composites, Coatings",
     "Graphene-enhanced materials at industrial scale.",
     "Dhatu Materials manufactures graphene nanoplatelets and composite masterbatches that make plastics, "
     "concrete and coatings stronger, lighter and more durable.",
     "Seed", 15 * CRORE, False, 0, True,
     [("Rakesh Hegde", "Founder & CEO"), ("Sanya Bhat", "Head of Materials")],
     [("DhatuGraph", "Graphene nanoplatelets."),
      ("DhatuCrete", "Graphene-enhanced concrete admixture.")]),
    ("Setu Sensors", "iot", "Kolkata", "West Bengal", 2020, "11-50",
     "Structural Health, Industrial IoT",
     "Wireless sensors that keep bridges and buildings safe.",
     "Setu Sensors installs wireless strain, vibration and tilt sensors on bridges, metros and high-rises, "
     "flagging structural problems long before they become dangerous.",
     "Seed", 9 * CRORE, True, 30 * CRORE, False,
     [("Souvik Banerjee", "Founder & CEO"), ("Ritika Das", "CTO")],
     [("SetuNode", "Battery-powered multi-sensor node."),
      ("BridgeWatch", "Structural health dashboard.")]),
    ("Pakshi Aerial", "drones", "Chandigarh", "Punjab", 2019, "51-200",
     "Agri Drones, Spraying, Mapping",
     "Precision spraying drones for Indian agriculture.",
     "Pakshi Aerial manufactures DGCA-certified agricultural drones and runs a drone-as-a-service network "
     "that sprays and maps millions of acres with less water and chemical use.",
     "Series A", 75 * CRORE, True, 100 * CRORE, True,
     [("Harpreet Singh", "Founder & CEO"), ("Simran Kaur", "COO")],
     [("Pakshi AG-10", "10-litre spraying drone."),
      ("FieldMap", "Drone mapping and crop analytics.")]),
]

INVESTORS = [
    ("Meru Ventures", "VC", "Bengaluru", "Early-stage deep-tech investor backing hard science founders.",
     5 * CRORE, 40 * CRORE, "Seed, Series A", ["spacetech", "semiconductors", "quantum", "ai"], True),
    ("Gangotri Deep Tech Fund", "VC", "Mumbai", "Growth capital for Indian climate and energy leaders.",
     25 * CRORE, 150 * CRORE, "Series A, Series B", ["clean-energy", "climatetech", "ev-mobility"], True),
    ("Kaveri Angels", "Angel Network", "Chennai", "200+ operator angels investing in frontier tech.",
     25 * LAKH, 3 * CRORE, "Pre-Seed, Seed", ["medtech", "biotech", "ai", "iot"], False),
    ("Sahyadri Capital", "VC", "Pune", "Seed fund for robotics, manufacturing and industrial AI.",
     2 * CRORE, 15 * CRORE, "Seed, Pre-Series A", ["robotics", "ai", "advanced-materials"], True),
    ("Indus Frontier Partners", "VC", "Delhi", "Strategic technologies for national resilience.",
     10 * CRORE, 80 * CRORE, "Series A, Series B", ["defence", "spacetech", "drones"], False),
    ("Navonmesh Accelerator", "Accelerator", "Hyderabad", "Six-month deep-tech accelerator with lab access.",
     25 * LAKH, 1 * CRORE, "Pre-Seed", ["biotech", "agritech", "medtech"], False),
]

UPDATES = {
    "Akashdeep Aerospace": [("Successful static fire of our cryogenic upper stage",
                             "Our upper-stage engine completed a 120-second full-duration static fire test."),
                            ("Opened a new integration facility in Hyderabad",
                             "The 60,000 sq ft facility can integrate four launch vehicles per year.")],
    "BharatAI": [("Sutra LLM now supports 22 languages", "Our latest release adds Bodo, Dogri and Santali.")],
    "UrjaNext": [("Commissioned 50 MWh storage project", "Our largest deployment to date is now live in Gujarat.")],
}


STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# Demo imagery (see tools/fetch_images.py, tools/generate_logos.py and
# static/images/photos/CREDITS.json). Replace with real uploads before launch.
FEMALE_NAMES = {"Meera", "Ananya", "Lakshmi", "Priya", "Neha", "Fatima", "Ritu", "Sunita", "Shalini", "Deepa",
                "Pooja", "Ayesha", "Sneha", "Nidhi", "Swati", "Farah", "Kriti", "Kavitha", "Anjali", "Shruti",
                "Divya", "Pallavi", "Sanya", "Ritika", "Simran", "Kavya"}


def _cover_variant(slug, n):
    return f"images/covers/{slug}.svg" if n == 1 else f"images/covers/{slug}-{n}.svg"


def _files(*parts):
    folder = os.path.join(STATIC_DIR, *parts)
    return sorted(f for f in os.listdir(folder) if f.endswith((".jpg", ".svg"))) if os.path.isdir(folder) else []


def _photo(cat, n):
    files = _files("images", "photos", cat)
    if not files:
        return _cover_variant(cat, (n % 3) + 1)
    return f"images/photos/{cat}/{files[n % len(files)]}"


def _logo(filename):
    return f"images/logos/{filename}" if os.path.exists(os.path.join(STATIC_DIR, "images", "logos", filename)) else None


class _Portraits:
    def __init__(self):
        people = _files("images", "people")
        self.pools = {"w": [f for f in people if f.startswith("w")], "m": [f for f in people if f.startswith("m")]}
        self.used = {"w": 0, "m": 0}

    def next(self, full_name):
        first = next((w for w in full_name.replace("(Retd.)", "").split() if not w.endswith(".")), "")
        kind = "w" if first in FEMALE_NAMES else "m"
        pool = self.pools[kind]
        if not pool:
            return None
        photo = pool[self.used[kind] % len(pool)]
        self.used[kind] += 1
        return f"images/people/{photo}"


def seed_database():
    if db.session.scalars(select(Category.id)).first():
        return "Database already contains data; run `flask seed --reset` to start over."

    rnd = random.Random(42)
    now = utcnow()
    db.session.add(BiddingRules(id=1))
    for key, value in PlatformSetting.DEFAULTS.items():
        PlatformSetting.set(key, value)

    users = {}
    for email, password, name, role in DEMO_ACCOUNTS:
        user = User(email=email, name=name, role=role, email_verified_at=now)
        user.set_password(password)
        db.session.add(user)
        users[role] = user

    categories = {}
    for order, (name, slug, icon, color, description) in enumerate(CATEGORIES):
        category = Category(name=name, slug=slug, icon=icon, color=color, description=description, sort_order=order)
        db.session.add(category)
        categories[slug] = category
    db.session.flush()

    startups = []
    portraits = _Portraits()
    per_category = {}
    for index, row in enumerate(STARTUPS):
        (name, cat, city, state, founded, team, tags, tagline, description,
         stage, raised, raising, target, verified, founders, products) = row
        k = per_category[cat] = per_category.get(cat, -1) + 1  # nth startup in this category
        slug = name.lower().replace(" ", "-").replace(".", "")
        startup = Startup(
            slug=slug, name=name, tagline=tagline, logo_path=_logo(f"{slug}.svg"), cover_path=_photo(cat, k),
            description=description, category_id=categories[cat].id, tags=tags, city=city, state=state,
            founded_year=founded, team_size=team,
            website=f"https://www.{name.lower().replace(' ', '')}.example",
            contact_email=f"hello@{name.lower().replace(' ', '')}.example",
            address=f"{city}, {state}, India", is_verified=verified, status="published",
            published_at=now - timedelta(days=index * 9 + 3), investor_pick=index % 4 == 1,
        )
        db.session.add(startup)
        db.session.flush()
        db.session.add(FundingProfile(
            startup_id=startup.id, is_raising=raising, stage=stage, total_raised_inr=raised,
            raising_target_inr=target, min_ticket_inr=50 * LAKH if raising else 0,
            use_of_funds="Scale manufacturing, expand R&D and grow the commercial team." if raising else "",
        ))
        for order, (founder_name, title) in enumerate(founders):
            db.session.add(Founder(startup_id=startup.id, name=founder_name, title=title, sort_order=order,
                                   bio=f"{title.split('&')[-1].strip()} at {name}.",
                                   linkedin_url="https://www.linkedin.com/", photo_path=portraits.next(founder_name)))
        for order, (product_name, summary) in enumerate(products):
            db.session.add(Product(startup_id=startup.id, name=product_name, summary=summary, sort_order=order,
                                   image_path=_photo(cat, k * 2 + order + 3)))
        for order in range(4):
            db.session.add(GalleryImage(startup_id=startup.id, image_path=_photo(cat, k + order + 1),
                                        caption=f"{name}: sample image {order + 1}", sort_order=order))
        for title, body in UPDATES.get(name, []):
            db.session.add(StartupUpdate(startup_id=startup.id, title=title, body=body,
                                         created_at=now - timedelta(days=rnd.randint(2, 40))))
        for day_offset in range(60):
            views = max(0, int(rnd.gauss(18 - index * 0.4, 6)) + (8 if day_offset < 30 else 0))
            if views:
                db.session.add(StartupView(startup_id=startup.id, day=date.today() - timedelta(days=day_offset),
                                           views=views))
        startups.append(startup)

    owner = users["startup_owner"]
    db.session.add(StartupMember(startup_id=startups[0].id, user_id=owner.id, role="owner"))

    for i, (firm, kind, city, thesis, cmin, cmax, stages, cats, verified) in enumerate(INVESTORS):
        if i == 0:
            user = users["investor"]
        else:
            user = User(email=f"sample.investor{i}@deeptechindia.local", name=f"{firm} (sample)", role="investor",
                        email_verified_at=now)
            user.set_password(f"unusable-{rnd.random()}-{rnd.random()}")
            db.session.add(user)
        db.session.flush()
        profile = InvestorProfile(user_id=user.id, firm_name=firm, investor_type=kind, city=city,
                                  thesis=thesis, check_min_inr=cmin, check_max_inr=cmax, stages=stages,
                                  is_verified=verified, website=f"https://{firm.lower().replace(' ', '')}.example",
                                  logo_path=_logo(f"investor-{firm.lower().replace(' ', '-')}.svg"))
        profile.categories = [categories[c] for c in cats]
        db.session.add(profile)
    db.session.flush()

    _seed_bids(startups, owner, now)
    db.session.commit()
    return (
        "Seeded SAMPLE data: "
        f"{len(CATEGORIES)} categories, {len(STARTUPS)} startups, {len(INVESTORS)} investors.\n"
        "Demo logins (development only):\n"
        + "\n".join(f"  {role:<14} {email} / {password}" for email, password, _, role in DEMO_ACCOUNTS)
    )


def _seed_bids(startups, owner, now):
    """Paid sample bids so the ranking and dashboard have something to show."""
    def paid_bid(startup, amount, position, days_ago, status=BID_ACTIVE, user=None):
        paid_at = now - timedelta(days=days_ago, hours=3)
        bid = Bid(startup_id=startup.id, user_id=user.id if user else None, target_position=position,
                  amount_paise=amount * 100, status=status, idempotency_key=f"seed-{startup.id}-{amount}-{days_ago}xx",
                  paid_at=paid_at, expires_at=paid_at + timedelta(days=30), achieved_position=position,
                  created_at=paid_at - timedelta(minutes=4))
        db.session.add(bid)
        db.session.flush()
        db.session.add(Payment(bid_id=bid.id, user_id=bid.user_id, startup_id=startup.id, provider="mock",
                               provider_order_id=f"order_seed_{bid.id}", provider_payment_id=f"pay_seed_{bid.id}",
                               receipt=f"DTI{bid.id:06d}SEED", amount_paise=bid.amount_paise, status=PAY_PAID,
                               method="upi", paid_at=paid_at, created_at=bid.created_at))
        db.session.add(RankingEvent(startup_id=startup.id, bid_id=bid.id, event_type="payment_confirmed",
                                    new_position=position, detail="Sample data", created_at=paid_at))
        return bid

    # The demo owner's own history (Akashdeep Aerospace).
    mine = startups[0]
    paid_bid(mine, 200, 5, 14, BID_SUPERSEDED, owner)
    paid_bid(mine, 300, 4, 11, BID_SUPERSEDED, owner)
    paid_bid(mine, 450, 3, 9, BID_SUPERSEDED, owner)
    failed = Bid(startup_id=mine.id, user_id=owner.id, target_position=2, amount_paise=90_000, status=BID_FAILED,
                 idempotency_key="seed-failed-attempt-0001", created_at=now - timedelta(days=8))
    cancelled = Bid(startup_id=mine.id, user_id=owner.id, target_position=2, amount_paise=90_000,
                    status=BID_CANCELLED, idempotency_key="seed-cancelled-attempt-01", created_at=now - timedelta(days=8))
    db.session.add_all([failed, cancelled])
    db.session.flush()
    db.session.add(Payment(bid_id=failed.id, user_id=owner.id, startup_id=mine.id, provider="mock",
                           provider_order_id=f"order_seed_{failed.id}", receipt=f"DTI{failed.id:06d}SEED",
                           amount_paise=90_000, status=PAY_FAILED, failure_reason="Payment declined (sample)",
                           created_at=failed.created_at))
    db.session.add(Payment(bid_id=cancelled.id, user_id=owner.id, startup_id=mine.id, provider="mock",
                           provider_order_id=f"order_seed_{cancelled.id}", receipt=f"DTI{cancelled.id:06d}SEED",
                           amount_paise=90_000, status=PAY_CANCELLED, created_at=cancelled.created_at))
    paid_bid(mine, 500, 3, 7, BID_ACTIVE, owner)

    # Other (sample) startups holding positions.
    for startup, amount, position, days in ((startups[3], 1500, 1, 6), (startups[5], 800, 2, 5),
                                            (startups[7], 300, 4, 4), (startups[9], 200, 5, 3),
                                            (startups[13], 100, 6, 2)):
        paid_bid(startup, amount, position, days)

    db.session.flush()
    ranking_service.recompute_rankings(ranking_service.get_rules(), now)

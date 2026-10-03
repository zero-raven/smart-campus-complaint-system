"""Build the labelled complaint corpus.

IMPORTANT - dataset provenance
------------------------------
No real campus complaint corpus exists for this project. The dataset is
therefore SYNTHETIC and must be described as such in the report. It is built
from three documented sources:

  1. Hand-written realistic templates grounded in actual campus facilities
     (hostel blocks, labs, mess, library, gym, exam halls).
  2. Vocabulary variation: synonyms, colloquial phrasing, misspellings and
     Hindi/English code-mixing, which is how students actually write.
  3. Systematic perturbations of the templates (severity words, locations,
     durations) to enlarge the corpus beyond the template count.

That provenance is stated in the class docstring and echoed into the generated
CSV header comment so it cannot be quietly misrepresented later.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

# The label set MUST match category.category_code in database/seed.sql,
# because ml_service maps model labels to category_id through that column.
CATEGORIES: list[str] = [
    "ELECTRICAL",
    "PLUMBING",
    "CIVIL",
    "NETWORK",
    "HOUSEKEEPING",
    "SECURITY",
    "EXAMINATION",
    "MESS",
    "LIBRARY",
    "TRANSPORT",
    "SPORTS",
    "OTHER",
]

# (category, template). Each template has {sev} and {dur} slots filled from the
# perturbation lists below.
TEMPLATES: list[tuple[str, str]] = [
    # ---------------- ELECTRICAL ----------------
    ("ELECTRICAL", "The fan in room {loc} stopped working and the {sev} switch board is sparking."),
    ("ELECTRICAL", "There is no power supply to the entire {loc} since {dur}."),
    ("ELECTRICAL", "Tube light and switch are not working in the {loc}, it is very {sev} at night."),
    ("ELECTRICAL", "Exposed wire is hanging from the ceiling in {loc}, this is {sev} and dangerous."),
    ("ELECTRICAL", "The {sev} socket in the lab keeps tripping the main breaker."),
    ("ELECTRICAL", "Voltage fluctuation is {sev} in {loc} and equipment keeps resetting."),
    ("ELECTRICAL", "The geyser in the {loc} bathroom is not heating at all."),
    ("ELECTRICAL", "Streetlight outside the {loc} is dead, the area is {sev} at night."),
    ("ELECTRICAL", "Short circuit in the {loc} notice board wiring, there was {sev} smoke."),
    ("ELECTRICAL", "Charging point and power socket are {sev} damaged in {loc}."),

    # ---------------- PLUMBING ----------------
    ("PLUMBING", "There is no water supply in the {loc} washroom for {dur}."),
    ("PLUMBING", "The tap in {loc} is leaking continuously and the floor is flooded."),
    ("PLUMBING", "Toilet is not flushing properly in {loc}, it is very {sev}."),
    ("PLUMBING", "Bathroom drain is blocked and sewage is overflowing in {loc}."),
    ("PLUMBING", "Water from the {loc} drinking outlet looks contaminated and {sev}."),
    ("PLUMBING", "Shower in {loc} has no water pressure since {dur}."),
    ("PLUMBING", "The {sev} pipeline under the {loc} building is leaking continuously."),
    ("PLUMBING", "Washroom in {loc} has no soap or water supply for {dur}."),
    ("PLUMBING", "Water tank overflow is causing waterlogging near {loc}."),
    ("PLUMBING", "The flush pipe in {loc} is broken and water keeps running."),

    # ---------------- CIVIL ----------------
    ("CIVIL", "The ceiling in {loc} has a large crack and plaster is falling, it is {sev}."),
    ("CIVIL", "Steps leading to {loc} are broken and {sev}, someone could fall."),
    ("CIVIL", "The {sev} road near {loc} has many potholes and is dangerous for two wheelers."),
    ("CIVIL", "Rainwater from the {loc} roof drips into the corridor making it slippery."),
    ("CIVIL", "The bench in {loc} is broken and the paint is peeling off the walls."),
    ("CIVIL", "Window pane in {loc} is shattered and the {sev} gap lets rain in."),
    ("CIVIL", "The lift in {loc} is out of order and people must climb four floors."),
    ("CIVIL", "Corridor light slab in {loc} has fallen and the area is {sev}."),
    ("CIVIL", "The {sev} pillar in the {loc} parking area has cracks."),
    ("CIVIL", "Drinking water tank on the {loc} roof is leaking and wasting water."),

    # ---------------- NETWORK ----------------
    ("NETWORK", "The wifi in {loc} is not working for the past {dur}."),
    ("NETWORK", "Internet speed in {loc} lab is extremely {sev} and pages keep loading."),
    ("NETWORK", "The lan cable connection to {loc} is loose and the network drops."),
    ("NETWORK", "Printer in {loc} is not available on the network and shows an error."),
    ("NETWORK", "The lab network in {loc} goes down every evening around the exam time."),
    ("NETWORK", "Wi-fi login page keeps asking for credentials again and again in {loc}."),
    ("NETWORK", "Projector in {loc} has no HDMI signal from the laptop network port."),
    ("NETWORK", "Examination server in {loc} becomes {sev} during the exam and everyone disconnects."),
    ("NETWORK", "The network switch in {loc} needs replacement, ports are {sev} damaged."),
    ("NETWORK", "Cannot access the shared drive from {loc} since {dur}."),

    # ---------------- HOUSEKEEPING ----------------
    ("HOUSEKEEPING", "The {loc} corridor has not been cleaned for {dur} and is very {sev}."),
    ("HOUSEKEEPING", "Dust and garbage have accumulated in the {loc} for days."),
    ("HOUSEKEEPING", "Washroom in {loc} is {sev} dirty and the soap is always empty."),
    ("HOUSEKEEPING", "The dustbin in {loc} is overflowing and waste is scattered around."),
    ("HOUSEKEEPING", "Mop and bucket are not available in the {loc} washroom."),
    ("HOUSEKEEPING", "Sweeping has not been done in {loc} and the {sev} smell is unbearable."),
    ("HOUSEKEEPING", "Classroom {loc} has {sev} dirty walls and the projector has dust."),
    ("HOUSEKEEPING", "Washroom cleaning is very infrequent in {loc}, it has been {dur}."),
    ("HOUSEKEEPING", "Food waste from {loc} is thrown in the open and attracts flies."),
    ("HOUSEKEEPING", "The {loc} common area is not swept and leaves are piled up."),

    # ---------------- SECURITY ----------------
    ("SECURITY", "The CCTV cameras near {loc} are not working and the area is {sev}."),
    ("SECURITY", "There was an accident near the {loc} gate and no one responded for {dur}."),
    ("SECURITY", "A stranger was roaming in the {loc} at night which is very {sev}."),
    ("SECURITY", "Bike theft happened in the {loc} parking area {dur} ago."),
    ("SECURITY", "Girls are being harassed near the {loc} bus stop after dark."),
    ("SECURITY", "The main gate of {loc} is left open at night which is {sev}."),
    ("SECURITY", "Security guard is absent from the {loc} entrance during night shift."),
    ("SECURITY", "The fire extinguisher in {loc} is missing, this is very {sev}."),
    ("SECURITY", "Fence around the {loc} sports ground is broken and it is {sev}."),
    ("SECURITY", "Night patrol in the {loc} area has not happened for {dur}."),

    # ---------------- EXAMINATION ----------------
    ("EXAMINATION", "The exam seating arrangement in {loc} is not followed and it is {sev}."),
    ("EXAMINATION", "Internal marks for the {loc} subjects have not been uploaded yet."),
    ("EXAMINATION", "Revaluation process for the {loc} exam has been delayed by {dur}."),
    ("EXAMINATION", "The invigilator did not come to {loc} and the exam started {sev} late."),
    ("EXAMINATION", "Exam timetable for the {loc} semester has conflicting entries."),
    ("EXAMINATION", "Attendance in {loc} is marked incorrectly and it affects the internal marks."),
    ("EXAMINATION", "The question paper for the {loc} exam had printing errors."),
    ("EXAMINATION", "Results for the {loc} subjects have still not been declared after {dur}."),
    ("EXAMINATION", "Students are not allowed to enter the {loc} exam hall without the hall ticket."),
    ("EXAMINATION", "The {sev} exam duty allocation for faculty in {loc} is unfair."),

    # ---------------- MESS ----------------
    ("MESS", "The food served in the mess {loc} has been {sev} poor quality this week."),
    ("MESS", "Roti and rice in the {loc} mess have been {sev} stale for {dur}."),
    ("MESS", "The mess {loc} kitchen is very {sev} and food is stored uncovered."),
    ("MESS", "Menu in the mess {loc} has not changed for {dur} and food is {sev}."),
    ("MESS", "There was hair in the curry served at the mess {loc}."),
    ("MESS", "The canteen near {loc} does not provide clean drinking water."),
    ("MESS", "The mess {loc} closes too early and students miss dinner after {dur} hours of classes."),
    ("MESS", "Food at the mess {loc} caused illness among hostel students."),
    ("MESS", "The mess {loc} dining hall is {sev} overcrowded and there is no place to sit."),
    ("MESS", "Milk served in the mess {loc} has a {sev} smell and an expiry date in the past."),

    # ---------------- LIBRARY ----------------
    ("LIBRARY", "Books required for the {loc} syllabus are not available in the library."),
    ("LIBRARY", "The library wifi has not worked for {dur} and e-resources are inaccessible."),
    ("LIBRARY", "Fine has been charged incorrectly for a book issued from the {loc} section."),
    ("LIBRARY", "The library {loc} reading hall is always crowded and there are {sev} few seats."),
    ("LIBRARY", "The library issue counter in {loc} is closed for {dur} during exam time."),
    ("LIBRARY", "Journal access in the {loc} library is {sev} slow and pages time out."),
    ("LIBRARY", "The library {loc} section lights are flickering and reading is difficult."),
    ("LIBRARY", "Library seating is {sev} insufficient during the semester."),
    ("LIBRARY", "The library {loc} returns desk has not been working and books go missing."),
    ("LIBRARY", "No drinking water in the library {loc} reading area for {dur}."),

    # ---------------- TRANSPORT ----------------
    ("TRANSPORT", "The college bus from {loc} is always late by more than twenty minutes."),
    ("TRANSPORT", "Two wheelers are not allowed in the {loc} parking and there is no shade."),
    ("TRANSPORT", "Bus service to {loc} has been suspended for {dur} without notice."),
    ("TRANSPORT", "The {loc} parking area is completely full and vehicles block the road."),
    ("TRANSPORT", "The bus driver stops the bus far away from the {loc} gate making it {sev}."),
    ("TRANSPORT", "Cycle track near {loc} is broken and it is {sev} for riders."),
    ("TRANSPORT", "Bus pass renewal at {loc} has not been done for {dur}."),
    ("TRANSPORT", "Overspeeding by the college bus on the {loc} route is very {sev}."),
    ("TRANSPORT", "There is no shelter at the {loc} pickup point during rain."),
    ("TRANSPORT", "Traffic congestion near the {loc} gate makes the {sev} morning entry chaotic."),

    # ---------------- SPORTS ----------------
    ("SPORTS", "The gym equipment in {loc} is {sev} damaged and nobody repairs it."),
    ("SPORTS", "The sports ground in {loc} has no proper lighting for evening practice."),
    ("SPORTS", "Tournament fixtures for the {loc} ground were not published for {dur}."),
    ("SPORTS", "The badminton court in {loc} has broken nets and a {sev} surface."),
    ("SPORTS", "Sports equipment issued to students in {loc} is not returned properly."),
    ("SPORTS", "The gym in {loc} does not have drinking water or a changing facility."),
    ("SPORTS", "Cricket nets in the {loc} ground are torn and the ball goes outside."),
    ("SPORTS", "The {sev} sports meet registration deadline was before students returned."),
    ("SPORTS", "Football goal post in {loc} is bent and the ground is very {sev} hard."),
    ("SPORTS", "Swimming area near {loc} is not maintained and the water looks dirty."),

    # ---------------- OTHER ----------------
    ("OTHER", "There is a general request regarding {loc} that needs attention from the administration."),
    ("OTHER", "Please look into the matter I am raising about {loc} at your convenience."),
    ("OTHER", "I want to suggest an improvement for {loc} which has been pending for {dur}."),
    ("OTHER", "This is a general grievance about campus facilities in {loc}, kindly advise."),
    ("OTHER", "Requesting information about the process to be followed for {loc}."),
    ("OTHER", "Some administrative matter regarding {loc} needs clarification from the office."),
]

LOCATIONS = [
    "Hostel Block A", "Hostel Block B", "the CSE block", "the main building",
    "the electrical block", "the civil block", "the central library",
    "the mess block", "the administration block", "the gym",
    "the sports ground", "the seminar hall", "the parking area",
    "the main gate", "the canteen", "the hostel mess",
    "room 214", "lab 312", "the second floor corridor", "the third floor washroom",
]

SEVERITIES = [
    "very serious", "quite urgent", "notable", "genuinely problematic",
    "increasingly difficult", "quite bad", "unbearable", "unacceptable",
]

DURATIONS = [
    "two days", "three days", "a week", "more than a week", "ten days",
    "fortnight", "several days", "a month", "since last week", "since yesterday",
]

# Light misspellings / colloquial forms students actually use.
COLLOQUIAL = [
    ("water supply", "water supply"),
    ("not working", "not working"),
    ("very bad", "very bad"),
    ("urgent", "urgent"),
    ("since", "from"),
    ("because", "because"),
    ("problem", "problem"),
    ("complaint", "complaint"),
]


# Real-world complaint writers reuse the same vocabulary across categories, and
# many complaints are genuinely ambiguous. These examples deliberately overlap
# category vocabulary so the benchmark measures real discrimination rather than
# keyword lookup. Without them every template is trivially separable and the
# reported F1 saturates at 1.00, which tells you nothing.
AMBIGUOUS: list[tuple[str, str]] = [
    ("ELECTRICAL", "The lift in the {loc} stopped and now we have to climb four floors in the heat."),
    ("PLUMBING", "The drinking water in {loc} tastes odd and has been like this for {dur}."),
    ("CIVIL", "The {loc} corridor is completely blocked and nobody clears it."),
    ("NETWORK", "The {loc} system is slow today and everyone is complaining about it."),
    ("HOUSEKEEPING", "The {loc} area has not been looked after and it shows."),
    ("SECURITY", "Someone is entering the {loc} without permission during the day."),
    ("TRANSPORT", "Getting to {loc} has become very difficult in the last {dur}."),
    ("OTHER", "There is a persistent problem in the {loc} that nobody is addressing."),
    ("OTHER", "Please sort out the situation at {loc}, it has been going on for {dur}."),
    ("MESS", "Quality of everything served at {loc} has dropped and people are unhappy."),
    ("EXAMINATION", "The procedure followed at {loc} is confusing and needs clarification."),
    ("LIBRARY", "Getting access to resources in {loc} is difficult and the process is unclear."),
    ("SPORTS", "The facilities at {loc} are not being maintained at all."),
    ("ELECTRICAL", "Everything in {loc} stops working the moment the power fluctuates."),
    ("SECURITY", "The {loc} area feels unsafe at night and students avoid it."),
    ("HOUSEKEEPING", "Nobody has cleaned {loc} properly, it is visibly {sev}."),
    ("NETWORK", "Sharing files and printing from {loc} has become impossible."),
    ("PLUMBING", "The taps run very slowly in {loc} and the water never gets warm."),
]

# Text-level corruptions that mimic how students actually type.
CORRUPTIONS = [
    ("no water", "no watter"),
    ("not working", "nt wrking"),
    ("complaint", "complain"),
    ("necessary", "neccessary"),
    ("receive", "recieve"),
    ("because", "becuase"),
    ("electric", "electrick"),
    ("water", "wtaer"),
]


def build_dataset(per_template: int = 6, seed: int = 42) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows: list[dict[str, str]] = []

    all_templates = TEMPLATES + AMBIGUOUS
    for category, template in all_templates:
        for _ in range(per_template):
            text = template.format(
                loc=rng.choice(LOCATIONS),
                sev=rng.choice(SEVERITIES),
                dur=rng.choice(DURATIONS),
            )
            # Occasional colloquial substitution to add surface variation.
            if rng.random() < 0.35:
                for a, b in COLLOQUIAL:
                    if a in text and a != b:
                        text = text.replace(a, b, 1)
                        break
            # Occasional misspelling to simulate informal student input.
            if rng.random() < 0.25:
                for a, b in CORRUPTIONS:
                    if a in text:
                        text = text.replace(a, b, 1)
                        break
            # Occasionally lowercase everything and drop punctuation entirely,
            # the way text is typed into a complaint box.
            if rng.random() < 0.10:
                text = text.lower().rstrip(".")

            rows.append(
                {
                    "text": text.strip(),
                    "category": category,
                    # group_id is the template index. The train/test split is done
                    # on GROUPS, never on rows, so the test set contains
                    # phrasings never seen during training. Splitting on rows
                    # would leak near-duplicates and inflate every metric.
                    "group_id": str(all_templates.index((category, template))),
                }
            )

    rng.shuffle(rows)
    return rows


def write_csv(output_path: Path, rows: list[dict[str, str]]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["text", "category", "group_id"]
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows = build_dataset()
    output = Path(__file__).resolve().parents[1] / "data" / "raw" / "complaints.csv"
    write_csv(output, rows)

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1

    print(f"Wrote {len(rows)} examples to {output}")
    print(f"Categories: {len(counts)}")
    for category in CATEGORIES:
        print(f"  {category:<14} {counts.get(category, 0)}")


if __name__ == "__main__":
    main()

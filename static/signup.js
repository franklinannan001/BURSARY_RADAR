const levelSelect = document.querySelector("#studyLevel");
const courseLabel = document.querySelector("#courseLabel");
const courseSelect = document.querySelector("#courseSelect");
const customCourseField = document.querySelector("#customCourseField");
const customCourse = document.querySelector("#customCourse");
const registrationForm = document.querySelector(".registration-form");

const gradeRanges = {
  Primary: [1, 6],
  "Junior Secondary": [7, 9],
  "Senior Secondary": [10, 12],
};

const tertiaryCourses = [
  "Computer Science",
  "Computer Engineering",
  "Civil Engineering",
  "Electrical Engineering",
  "Mechanical Engineering",
  "Information Technology",
  "Education",
  "Nursing",
  "Medicine",
  "Law",
  "Business Administration",
  "Accounting",
  "Agriculture",
  "Other",
];

function setCourseOptions(level) {
  courseSelect.replaceChildren();
  customCourseField.hidden = true;
  customCourse.required = false;
  customCourse.value = "";

  if (Object.prototype.hasOwnProperty.call(gradeRanges, level)) {
    courseLabel.textContent = "Grade:";
    const [first, last] = gradeRanges[level];
    courseSelect.add(new Option("Select a grade", ""));
    for (let grade = first; grade <= last; grade += 1) {
      courseSelect.add(new Option(`Grade ${grade}`, `Grade ${grade}`));
    }
    courseSelect.disabled = false;
    return;
  }

  if (level === "Tertiary") {
    courseLabel.textContent = "Course:";
    courseSelect.add(new Option("Select a course", ""));
    tertiaryCourses.forEach((course) => courseSelect.add(new Option(course, course)));
    courseSelect.disabled = false;
    return;
  }

  courseLabel.textContent = "Grade or course:";
  courseSelect.add(new Option("Select your level first", ""));
  courseSelect.disabled = true;
}

levelSelect.addEventListener("change", () => {
  setCourseOptions(levelSelect.value);
});

courseSelect.addEventListener("change", () => {
  const isOther = levelSelect.value === "Tertiary" && courseSelect.value === "Other";
  customCourseField.hidden = !isOther;
  customCourse.required = isOther;
  if (isOther) customCourse.focus();
});

registrationForm.addEventListener("reset", () => {
  window.setTimeout(() => setCourseOptions(levelSelect.value), 0);
});

setCourseOptions(levelSelect.value);

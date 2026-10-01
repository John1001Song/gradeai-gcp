# Exam: PHYS 101 Midterm 1

The instructor writes this file once, at course setup. Grade AI keeps **only**
the answer areas listed below. Everything else on the page (the name and
student ID header, page footers, margins) is dropped before any model sees it.

- course: PHYS 101
- pages: 1
- confidence_threshold: 0.80
- spot_check_rate: 0.10

## Q1: Projectile range (10 pts)

- page: 1
- region: [0.05, 0.18, 0.95, 0.55]
- prompt: A ball is launched at 20 m/s at 30 degrees above level ground. Find its horizontal range. Use g = 9.8 m/s^2.
- answer: R = v^2 sin(2θ) / g = 400 · sin(60°) / 9.8 ≈ 35.3 m

### Rubric

- (3) Uses the range equation or equivalent kinematics [keywords: sin(2θ) | sin 2θ | sin(60]
- (3) Substitutes v = 20 m/s and θ = 30° correctly [keywords: 400 | 20^2]
- (2) Correct numeric result, about 35 m [keywords: 35.3 | 35]
- (2) States units of meters [keywords: 3 m | meters]

## Q2: Block on an incline (10 pts)

- page: 1
- region: [0.05, 0.58, 0.95, 0.95]
- prompt: A 2 kg block rests on a frictionless incline at 25 degrees. Find its acceleration down the incline.
- answer: a = g sin(25°) ≈ 4.14 m/s^2

### Rubric

- (4) Free-body diagram resolves gravity along the incline [keywords: mg sin | g sin]
- (3) Recognizes mass cancels [keywords: cancels | m cancels | independent of mass]
- (3) Correct result, about 4.1 m/s^2 [keywords: 4.14 | 4.1]

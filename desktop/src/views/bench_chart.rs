//! The benchmark graph and the ranked bars.
//!
//! The graph: how well each model reads (up) against what it costs, cheapest on the right,
//! so the most efficient models sit in the top-right corner. One model's sizes are joined
//! by a line in their engine's colour and labelled once, at the best of them.
//!
//! The bars: every model's score with its 95% interval, beside what it costs. They are also
//! the graph's table: every value the graph plots is written there.

use gpui_kit::component::{ActiveTheme, StyledExt};
use gpui_kit::prelude::FluentBuilder as _;
use gpui_kit::*;


/// At most three hues, validated as a set for colour-blind readers in every pairing; every
/// other engine shares the neutral. Colour follows the engine, never the rank.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Series {
    Paddle,
    Tesseract,
    Ollama,
    Other,
}

impl Series {
    pub const ORDER: [Series; 4] = [Series::Paddle, Series::Tesseract, Series::Ollama, Series::Other];

    pub fn of(engine: &str) -> Series {
        match engine {
            "paddleocr" | "paddleocr-vl" => Series::Paddle,
            "tesseract" => Series::Tesseract,
            "ollama" => Series::Ollama,
            _ => Series::Other,
        }
    }

    pub fn label(self) -> &'static str {
        match self {
            Series::Paddle => "PaddleOCR",
            Series::Tesseract => "Tesseract",
            Series::Ollama => "Ollama",
            Series::Other => "Other engines",
        }
    }

    pub fn color(self) -> Hsla {
        rgb(match self {
            Series::Paddle => 0x3987e5,
            Series::Tesseract => 0xd95926,
            Series::Ollama => 0x199e70,
            Series::Other => 0x898781,
        })
        .into()
    }
}

#[derive(Clone, Debug)]
pub struct ChartPoint {
    pub id: String,
    /// In full; heads the tooltip.
    pub name: String,
    /// Points of one family are joined by a line.
    pub family: String,
    /// The family's label on the graph.
    pub label: String,
    pub variant: Option<String>,
    pub series: Series,
    pub x: f64,
    pub y: f64,
    /// Drawn as a ring: a published score for a model that isn't installed here.
    pub hollow: bool,
    /// Tooltip rows: (label, value).
    pub rows: Vec<(String, String)>,
}

// --- scales -----------------------------------------------------------------------------

/// 1-2-5 steps: the log axis only shows values people read at a glance.
pub fn step125(v: f64, up: bool) -> f64 {
    let p = 10f64.powf(v.log10().floor());
    let steps = [p, 2.0 * p, 5.0 * p, 10.0 * p];
    if up {
        steps.into_iter().find(|s| *s >= v * (1.0 - 1e-9)).unwrap_or(10.0 * p)
    } else {
        steps.into_iter().rev().find(|s| *s <= v * (1.0 + 1e-9)).unwrap_or(p)
    }
}

pub fn log_domain(values: &[f64]) -> (f64, f64) {
    let lo = values.iter().cloned().fold(f64::INFINITY, f64::min).max(1e-3);
    let hi = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max).max(lo);
    (step125(lo / 1.15, false), step125(hi * 1.15, true))
}

pub fn log_ticks((lo, hi): (f64, f64)) -> Vec<f64> {
    let mut ticks = Vec::new();
    for p in (lo.log10().floor() as i32)..=(hi.log10().ceil() as i32) {
        for m in [1.0, 2.0, 5.0] {
            let t = m * 10f64.powi(p);
            if t >= lo * 0.999 && t <= hi * 1.001 {
                ticks.push(t);
            }
        }
    }
    if ticks.len() > 7 {
        ticks.retain(|t| (t.log10().rem_euclid(1.0)).abs() < 1e-9 || *t == lo || *t == hi);
    }
    ticks
}

pub fn linear_domain(values: &[f64], cap: f64) -> ((f64, f64), Vec<f64>) {
    let mut lo = values.iter().cloned().fold(f64::INFINITY, f64::min);
    let mut hi = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let pad = ((hi - lo) * 0.18).max(cap * 0.02);
    lo = (lo - pad).max(0.0);
    hi = (hi + pad).min(cap);
    let span = hi - lo;
    let step = [1.0, 2.0, 5.0, 10.0, 20.0, 25.0, 50.0, 100.0, 200.0]
        .into_iter()
        .map(|s| s * cap / 100.0)
        .find(|s| span / s <= 5.0)
        .unwrap_or(cap / 5.0);
    let d0 = (lo / step).floor() * step;
    let d1 = ((hi / step).ceil() * step).min(cap);
    let mut ticks = Vec::new();
    let mut t = d0;
    while t <= d1 + step / 1000.0 {
        ticks.push((t * 1e6).round() / 1e6);
        t += step;
    }
    ((d0, d1), ticks)
}

/// Axis ticks in round decimal units (5,000 MB reads "5 GB", not "4.9 GB").
pub fn mb_tick(v: f64) -> String {
    if v >= 1000.0 { format!("{} GB", trim(v / 1000.0, 1)) } else { format!("{} MB", trim(v, 0)) }
}

pub fn sec_tick(v: f64) -> String {
    format!("{} s", if v < 1.0 { trim(v, 2) } else { trim(v, 1) })
}

/// A number with at most `digits` decimals and no trailing zeros.
fn trim(v: f64, digits: usize) -> String {
    let s = format!("{v:.digits$}");
    if s.contains('.') { s.trim_end_matches('0').trim_end_matches('.').to_string() } else { s }
}

// --- labels -----------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
struct Rect {
    x1: f32,
    y1: f32,
    x2: f32,
    y2: f32,
}

fn overlap(a: Rect, b: Rect) -> f32 {
    (a.x2.min(b.x2) - a.x1.max(b.x1)).max(0.0) * (a.y2.min(b.y2) - a.y1.max(b.y1)).max(0.0)
}

struct Placed {
    point: usize,
    rect: Rect,
    /// Pushed away from its point: drawn with a hairline back to it.
    leader: bool,
}

// Average glyph widths, to place labels before they render.
const LABEL_PX: f32 = 7.1;
const VARIANT_PX: f32 = 7.2;
const RINGS: [f32; 4] = [11.0, 30.0, 52.0, 76.0];

/// One label per family, at its best point. Spots are tried nearest first (above, right,
/// left, below, then the diagonals, at growing distances), keeping clear of the plot's
/// edges, every point and the labels already placed; with no clear spot, the one that
/// overlaps least is used.
fn place_labels(points: &[ChartPoint], pos: &[(f32, f32)], lines: &[Vec<usize>], bounds: Rect) -> Vec<Placed> {
    let mut anchors: Vec<usize> = Vec::new();
    for (i, p) in points.iter().enumerate() {
        match anchors.iter().position(|&a| points[a].family == p.family) {
            Some(k) => {
                let a = anchors[k];
                if p.y > points[a].y || (p.y == points[a].y && pos[i].0 > pos[a].0) {
                    anchors[k] = i;
                }
            }
            None => anchors.push(i),
        }
    }
    let mut obstacles: Vec<Rect> =
        pos.iter().map(|&(x, y)| Rect { x1: x - 7.0, y1: y - 7.0, x2: x + 7.0, y2: y + 7.0 }).collect();
    // The family lines too, as small boxes every 6px along them.
    for members in lines {
        for w in members.windows(2) {
            let ((ax, ay), (bx, by)) = (pos[w[0]], pos[w[1]]);
            let steps = (((bx - ax).hypot(by - ay)) / 6.0).ceil().max(1.0) as i32;
            for k in 0..=steps {
                let t = k as f32 / steps as f32;
                let (x, y) = (ax + (bx - ax) * t, ay + (by - ay) * t);
                obstacles.push(Rect { x1: x - 2.0, y1: y - 2.0, x2: x + 2.0, y2: y + 2.0 });
            }
        }
    }
    anchors.sort_by(|a, b| pos[*a].1.total_cmp(&pos[*b].1));
    let mut placed: Vec<Placed> = Vec::new();
    for i in anchors {
        let p = &points[i];
        let w = (p.label.chars().count() as f32 * LABEL_PX)
            .max(p.variant.as_ref().map_or(0, |v| v.chars().count()) as f32 * VARIANT_PX);
        let h = if p.variant.is_some() { 27.0 } else { 15.0 };
        let (px_, py_) = pos[i];
        let mut spots: Vec<(Rect, bool)> = Vec::new();
        for d in RINGS {
            let at = |x: f32, y: f32| (Rect { x1: x, y1: y, x2: x + w, y2: y + h }, d == RINGS[0]);
            spots.extend([
                at(px_ - w / 2.0, py_ - d - h),
                at(px_ + d, py_ - h / 2.0),
                at(px_ - d - w, py_ - h / 2.0),
                at(px_ - w / 2.0, py_ + d),
                at(px_ + d * 0.7, py_ - d * 0.7 - h),
                at(px_ - d * 0.7 - w, py_ - d * 0.7 - h),
                at(px_ + d * 0.7, py_ + d * 0.7),
                at(px_ - d * 0.7 - w, py_ + d * 0.7),
            ]);
        }
        let clash = |r: Rect| -> f32 {
            placed.iter().map(|q| overlap(q.rect, r)).sum::<f32>() + obstacles.iter().map(|o| overlap(*o, r)).sum::<f32>()
        };
        let inside: Vec<(Rect, bool)> = spots
            .iter()
            .copied()
            .filter(|(r, _)| r.x1 >= bounds.x1 && r.x2 <= bounds.x2 && r.y1 >= bounds.y1 && r.y2 <= bounds.y2)
            .collect();
        let pick = inside
            .iter()
            .copied()
            .find(|(r, _)| clash(*r) == 0.0)
            .or_else(|| inside.iter().copied().min_by(|a, b| clash(a.0).total_cmp(&clash(b.0))))
            .unwrap_or(spots[0]);
        placed.push(Placed { point: i, rect: pick.0, leader: !pick.1 });
    }
    placed
}

// --- the graph --------------------------------------------------------------------------

pub const CHART_W: f32 = 760.0;
const CHART_H: f32 = 420.0;
const M_TOP: f32 = 52.0;
const M_RIGHT: f32 = 28.0;
const M_BOTTOM: f32 = 54.0;
const M_LEFT: f32 = 54.0;
const DOT_R: f32 = 4.5;

pub struct ChartSpec {
    pub title: String,
    pub x_label: String,
    pub x_format: fn(f64) -> String,
    pub y_format: fn(f64) -> String,
    /// Highest possible y (100 for a percentage).
    pub y_cap: f64,
}

/// The graph, `active` the point under the pointer (its family is drawn on top, the rest
/// faded). `on_hover` reports the point the pointer enters or leaves.
pub fn chart(
    points: &[ChartPoint],
    spec: &ChartSpec,
    active: Option<&str>,
    on_hover: impl Fn(Option<String>, &mut Window, &mut App) + Clone + 'static,
    cx: &App,
) -> Div {
    let plot_w = CHART_W - M_LEFT - M_RIGHT;
    let plot_h = CHART_H - M_TOP - M_BOTTOM;
    let xs: Vec<f64> = points.iter().map(|p| p.x).collect();
    let ys: Vec<f64> = points.iter().map(|p| p.y).collect();
    let x_domain = log_domain(&xs);
    let x_ticks = log_ticks(x_domain);
    let (y_domain, y_ticks) = linear_domain(&ys, spec.y_cap);
    let log_span = (x_domain.1.log10() - x_domain.0.log10()).max(1e-9);
    // Reversed: the cheapest end of the axis is on the right.
    let sx = move |v: f64| M_LEFT + ((1.0 - (v.log10() - x_domain.0.log10()) / log_span) as f32) * plot_w;
    let y_span = if y_domain.1 - y_domain.0 == 0.0 { 1.0 } else { y_domain.1 - y_domain.0 };
    let sy = move |v: f64| M_TOP + ((1.0 - (v - y_domain.0) / y_span) as f32) * plot_h;
    let pos: Vec<(f32, f32)> = points.iter().map(|p| (sx(p.x), sy(p.y))).collect();

    // One line per family, through its sizes (largest first along the axis).
    let mut families: Vec<Vec<usize>> = Vec::new();
    for (i, p) in points.iter().enumerate() {
        match families.iter_mut().find(|f| points[f[0]].family == p.family) {
            Some(f) => f.push(i),
            None => families.push(vec![i]),
        }
    }
    for f in &mut families {
        f.sort_by(|a, b| points[*b].x.total_cmp(&points[*a].x));
    }
    let lines: Vec<Vec<usize>> = families.iter().filter(|f| f.len() > 1).cloned().collect();
    let labels = place_labels(
        points,
        &pos,
        &lines,
        Rect { x1: M_LEFT - 8.0, y1: M_TOP - 4.0, x2: CHART_W - 4.0, y2: CHART_H - M_BOTTOM - 2.0 },
    );

    let active_family = active.and_then(|id| points.iter().find(|p| p.id == id)).map(|p| p.family.clone());
    let fade = |family: &str| if active_family.as_deref().is_some_and(|f| f != family) { 0.28 } else { 1.0 };

    let grid = cx.theme().border;
    let axis = cx.theme().muted_foreground;
    let surface = cx.theme().background;
    let paint_lines: Vec<(Vec<(f32, f32)>, Hsla, f32, f32)> = lines
        .iter()
        .map(|f| {
            let family = &points[f[0]].family;
            let width = if active_family.as_ref() == Some(family) { 3.0 } else { 2.0 };
            (f.iter().map(|&i| pos[i]).collect(), points[f[0]].series.color(), width, fade(family))
        })
        .collect();
    let leaders: Vec<((f32, f32), (f32, f32), Hsla, f32)> = labels
        .iter()
        .filter(|l| l.leader)
        .map(|l| {
            let (px_, py_) = pos[l.point];
            let ex = px_.clamp(l.rect.x1, l.rect.x2);
            let ey = py_.clamp(l.rect.y1, l.rect.y2);
            let p = &points[l.point];
            ((px_, py_), (ex, ey), p.series.color(), 0.7 * fade(&p.family))
        })
        .collect();
    let dots: Vec<((f32, f32), Hsla, bool, f32, f32)> = points
        .iter()
        .zip(&pos)
        .map(|(p, &xy)| {
            let r = if active == Some(p.id.as_str()) { DOT_R + 1.5 } else { DOT_R };
            (xy, p.series.color(), p.hollow, r, fade(&p.family))
        })
        .collect();
    let y_lines: Vec<f32> = y_ticks.iter().map(|t| sy(*t)).collect();
    let x_lines: Vec<f32> = x_ticks.iter().map(|t| sx(*t)).collect();

    let drawing = canvas(
        |_, _, _| (),
        move |bounds, _, window, _| {
            let o = bounds.origin;
            let at = |x: f32, y: f32| point(o.x + px(x), o.y + px(y));
            let segment = |a: (f32, f32), b: (f32, f32), width: f32, color: Hsla, window: &mut Window| {
                let mut path = PathBuilder::stroke(px(width));
                path.move_to(at(a.0, a.1));
                path.line_to(at(b.0, b.1));
                if let Ok(path) = path.build() {
                    window.paint_path(path, color);
                }
            };
            for y in &y_lines {
                segment((M_LEFT, *y), (CHART_W - M_RIGHT, *y), 1.0, grid, window);
            }
            for x in &x_lines {
                segment((*x, M_TOP), (*x, CHART_H - M_BOTTOM), 1.0, grid.opacity(0.6), window);
            }
            segment((M_LEFT, CHART_H - M_BOTTOM), (CHART_W - M_RIGHT, CHART_H - M_BOTTOM), 1.0, axis.opacity(0.5), window);
            for (pts, color, width, alpha) in &paint_lines {
                let mut path = PathBuilder::stroke(px(*width));
                path.move_to(at(pts[0].0, pts[0].1));
                for p in &pts[1..] {
                    path.line_to(at(p.0, p.1));
                }
                if let Ok(path) = path.build() {
                    window.paint_path(path, color.opacity(*alpha));
                }
            }
            for (a, b, color, alpha) in &leaders {
                segment(*a, *b, 1.0, color.opacity(*alpha), window);
            }
            for ((x, y), color, hollow, r, alpha) in &dots {
                let r = *r;
                let bounds = Bounds { origin: at(x - r - 1.0, y - r - 1.0), size: size(px(2.0 * r + 2.0), px(2.0 * r + 2.0)) };
                let (fill_c, border) = if *hollow { (surface, color.opacity(*alpha)) } else { (color.opacity(*alpha), surface) };
                window.paint_quad(fill(bounds, fill_c).corner_radii(px(r + 1.0)).border_widths(px(2.0)).border_color(border));
            }
        },
    )
    .absolute()
    .top_0()
    .left_0()
    .size_full();

    let muted = cx.theme().muted_foreground;
    let mut chart = div()
        .relative()
        .w(px(CHART_W))
        .h(px(CHART_H))
        .flex_none()
        .child(drawing)
        .child(div().absolute().left(px(M_LEFT - 6.0)).top(px(10.)).text_sm().font_semibold().child(spec.title.clone()))
        .child(
            div()
                .absolute()
                .right(px(M_RIGHT))
                .top(px(12.))
                .text_xs()
                .italic()
                .text_color(muted)
                .child("most efficient ↗"),
        )
        .child(
            div()
                .absolute()
                .left(px(M_LEFT))
                .w(px(plot_w))
                .top(px(CHART_H - 22.0))
                .h_flex()
                .justify_center()
                .text_xs()
                .text_color(muted)
                .child(format!("{} · log scale, cheaper to the right", spec.x_label)),
        );
    for t in &y_ticks {
        chart = chart.child(
            div()
                .absolute()
                .left(px(0.))
                .w(px(M_LEFT - 10.0))
                .top(px(sy(*t) - 8.0))
                .h_flex()
                .justify_end()
                .text_xs()
                .text_color(muted)
                .child((spec.y_format)(*t)),
        );
    }
    for t in &x_ticks {
        chart = chart.child(
            div()
                .absolute()
                .left(px(sx(*t) - 40.0))
                .w(px(80.))
                .top(px(CHART_H - M_BOTTOM + 8.0))
                .h_flex()
                .justify_center()
                .text_xs()
                .text_color(muted)
                .child((spec.x_format)(*t)),
        );
    }
    for l in &labels {
        let p = &points[l.point];
        let alpha = fade(&p.family);
        chart = chart.child(
            div()
                .absolute()
                .left(px(l.rect.x1))
                .top(px(l.rect.y1))
                .v_flex()
                .opacity(alpha)
                .child(div().text_xs().font_semibold().whitespace_nowrap().child(p.label.clone()))
                .when_some(p.variant.clone(), |d, v| {
                    d.child(div().text_size(px(10.)).whitespace_nowrap().text_color(muted).child(v.to_uppercase()))
                }),
        );
    }
    // Hit targets bigger than the marks, on top of everything.
    for (p, (x, y)) in points.iter().zip(&pos) {
        let enter = on_hover.clone();
        let id = p.id.clone();
        chart = chart.child(
            div()
                .id(SharedString::from(format!("pt-{}", p.id)))
                .absolute()
                .left(px(x - 12.0))
                .top(px(y - 12.0))
                .size(px(24.))
                .rounded_full()
                .on_hover(move |hovered, window, cx| enter(if *hovered { Some(id.clone()) } else { None }, window, cx)),
        );
    }
    if let Some(p) = active.and_then(|id| points.iter().find(|p| p.id == id)) {
        let i = points.iter().position(|q| q.id == p.id).unwrap_or(0);
        let (x, y) = pos[i];
        chart = chart.child(
            tooltip_card(&p.name, p.series, &p.rows, cx)
                .absolute()
                .left(px((x + 16.0).clamp(8.0, CHART_W - 264.0)))
                .top(px((y - 20.0).clamp(4.0, CHART_H - 150.0))),
        );
    }
    chart
}

/// The tooltip for a point or a bar: the name with its series swatch, then its figures.
pub fn tooltip_card(name: &str, series: Series, rows: &[(String, String)], cx: &App) -> Div {
    let mut list = div().v_flex().gap_0p5();
    for (k, v) in rows {
        list = list.child(
            div()
                .h_flex()
                .justify_between()
                .gap_3()
                .child(div().text_color(cx.theme().muted_foreground).child(k.clone()))
                .child(div().font_medium().child(v.clone())),
        );
    }
    div()
        .w(px(256.))
        .v_flex()
        .gap_1()
        .px_3()
        .py_2()
        .rounded_lg()
        .border_1()
        .border_color(cx.theme().border)
        .bg(cx.theme().popover)
        .shadow_lg()
        .text_xs()
        .child(
            div()
                .h_flex()
                .gap_2()
                .font_medium()
                .child(div().w(px(14.)).h(px(3.)).rounded_full().bg(series.color()))
                .child(name.to_string()),
        )
        .child(list)
}

pub fn legend(series: &[Series], cx: &App) -> Option<Div> {
    if series.len() < 2 {
        return None;
    }
    let mut row = div().h_flex().flex_wrap().gap_4();
    for s in series {
        row = row.child(
            div()
                .h_flex()
                .gap_1()
                .text_xs()
                .text_color(cx.theme().muted_foreground)
                .child(div().w(px(14.)).h(px(3.)).rounded_full().bg(s.color()))
                .child(s.label()),
        );
    }
    Some(row)
}

// --- the bars ---------------------------------------------------------------------------

pub struct BarRow {
    pub id: String,
    pub name: String,
    pub label: String,
    pub variant: Option<String>,
    pub series: Series,
    /// The bar, as a fraction of the axis; None draws none.
    pub value: Option<f64>,
    /// Ends of the 95% interval, as fractions of the axis.
    pub low: Option<f64>,
    pub high: Option<f64>,
    /// The score as written, and its margin.
    pub display: String,
    pub margin: Option<String>,
    /// The other columns, in `headers` order.
    pub cells: Vec<AnyElement>,
    pub details: Vec<(String, String)>,
    /// A short line under the name, e.g. failed pages.
    pub note: Option<String>,
    pub action: Option<AnyElement>,
}

const TICKS: [f64; 5] = [0.0, 0.25, 0.5, 0.75, 1.0];

pub fn bars(
    rows: Vec<BarRow>,
    value_header: &str,
    headers: &[&str],
    tick_format: impl Fn(f64) -> String,
    with_actions: bool,
    active: Option<&str>,
    on_hover: impl Fn(Option<String>, &mut Window, &mut App) + Clone + 'static,
    cx: &App,
) -> Div {
    let muted = cx.theme().muted_foreground;
    let head = |text: String| div().text_xs().font_medium().text_color(muted).child(text.to_uppercase());
    let mut header = div()
        .h_flex()
        .gap_3()
        .py_2()
        .child(head("Model".into()).w(px(220.)))
        .child(div().flex_1().min_w(px(160.)))
        .child(head(value_header.to_string()).w(px(96.)).h_flex().justify_end());
    for h in headers {
        header = header.child(head(h.to_string()).w(px(96.)).h_flex().justify_end());
    }
    if with_actions {
        header = header.child(div().w(px(124.)));
    }
    let mut table = div().v_flex().child(header);
    for r in rows {
        let is_active = active == Some(r.id.as_str());
        let enter = on_hover.clone();
        let id = r.id.clone();
        let track = cx.theme().muted;
        let mark = cx.theme().foreground.opacity(0.8);
        let bar = div()
            .relative()
            .h(px(10.))
            .w_full()
            .rounded(px(4.))
            .bg(track)
            .when_some(r.value, |d, v| {
                d.child(
                    div()
                        .absolute()
                        .top_0()
                        .bottom_0()
                        .left_0()
                        .w(relative(v.clamp(0.0, 1.0) as f32))
                        .rounded(px(4.))
                        .bg(if is_active { r.series.color().opacity(0.85) } else { r.series.color() }),
                )
            })
            .when(r.low.is_some() && r.high.is_some(), |d| {
                let (lo, hi) = (r.low.unwrap().clamp(0.0, 1.0), r.high.unwrap().clamp(0.0, 1.0));
                d.child(
                    div()
                        .absolute()
                        .top(px(0.5))
                        .h(px(9.))
                        .left(relative(lo as f32))
                        .w(relative((hi - lo).max(0.0) as f32))
                        .border_l(px(1.5))
                        .border_r(px(1.5))
                        .border_color(mark)
                        .child(div().absolute().left_0().right_0().top(px(3.75)).h(px(1.5)).bg(mark)),
                )
            });
        let mut row = div()
            .id(SharedString::from(format!("bar-{}", r.id)))
            .relative()
            .h_flex()
            .gap_3()
            .py_2()
            .border_t_1()
            .border_color(cx.theme().border)
            .when(is_active, |d| d.bg(cx.theme().muted.opacity(0.5)))
            .on_hover(move |hovered, window, cx| enter(if *hovered { Some(id.clone()) } else { None }, window, cx))
            .child(
                div()
                    .v_flex()
                    .w(px(220.))
                    .child(
                        div()
                            .h_flex()
                            .flex_wrap()
                            .gap_1()
                            .text_sm()
                            .child(div().font_medium().child(r.label.clone()))
                            .when_some(r.variant.clone(), |d, v| {
                                d.child(div().text_color(muted).child(format!("[{}]", v.to_lowercase())))
                            }),
                    )
                    .when_some(r.note.clone(), |d, n| d.child(div().text_xs().text_color(cx.theme().danger).child(n))),
            )
            .child(div().flex_1().min_w(px(160.)).child(bar))
            .child(
                div()
                    .w(px(96.))
                    .h_flex()
                    .justify_end()
                    .gap_1()
                    .text_sm()
                    .child(div().font_medium().child(r.display.clone()))
                    .when_some(r.margin.clone(), |d, m| d.child(div().text_xs().text_color(muted).child(m))),
            );
        for cell in r.cells {
            row = row.child(div().w(px(96.)).h_flex().justify_end().text_sm().text_color(muted).child(cell));
        }
        if with_actions {
            row = row.child(div().w(px(124.)).h_flex().justify_end().when_some(r.action, |d, a| d.child(a)));
        }
        if is_active {
            row = row.child(tooltip_card(&r.name, r.series, &r.details, cx).absolute().top(px(36.)).left(px(232.)));
        }
        table = table.child(row);
    }
    // The axis under the bars.
    let mut axis = div().relative().h(px(16.)).flex_1().min_w(px(160.));
    for t in TICKS {
        let label = div().absolute().text_xs().text_color(muted).child(tick_format(t));
        axis = axis.child(if t == 0.0 {
            label.left_0()
        } else if t == 1.0 {
            label.right_0()
        } else {
            label.left(relative(t as f32)).ml(px(-12.))
        });
    }
    let mut foot = div().h_flex().gap_3().pt_1().child(div().w(px(220.))).child(axis).child(div().w(px(96.)));
    for _ in headers {
        foot = foot.child(div().w(px(96.)));
    }
    if with_actions {
        foot = foot.child(div().w(px(124.)));
    }
    table.child(foot)
}

/// "±2.1" in percentage points; whole points once it's 10 or more.
pub fn plus_minus(margin: Option<f64>) -> Option<String> {
    let points = margin? * 100.0;
    Some(if points < 10.0 { format!("±{points:.1}") } else { format!("±{}", points.round() as i64) })
}

pub fn pct(v: Option<f64>) -> String {
    v.map_or("–".into(), |v| format!("{:.1}%", v * 100.0))
}

pub fn secs(v: Option<f64>, digits: Option<usize>) -> String {
    v.map_or("–".into(), |v| {
        let d = digits.unwrap_or(if v >= 10.0 { 1 } else { 2 });
        format!("{v:.d$} s")
    })
}

pub fn mb(v: Option<f64>) -> String {
    v.map_or("–".into(), crate::format::mb)
}

#[cfg(test)]
mod tests {
    use super::{ChartPoint, Rect, Series, linear_domain, log_domain, log_ticks, mb_tick, place_labels, plus_minus, sec_tick, step125};

    #[test]
    fn log_axis_uses_one_two_five_steps() {
        assert_eq!(step125(3.0, true), 5.0);
        assert_eq!(step125(3.0, false), 2.0);
        assert_eq!(step125(0.07, true), 0.1);
        let domain = log_domain(&[0.4, 3.5]);
        assert_eq!(domain, (0.2, 5.0));
        assert_eq!(log_ticks(domain), vec![0.2, 0.5, 1.0, 2.0, 5.0]);
    }

    #[test]
    fn linear_axis_stays_within_its_cap() {
        let ((lo, hi), ticks) = linear_domain(&[88.0, 97.0], 100.0);
        assert!(lo >= 0.0 && hi <= 100.0, "{lo} {hi}");
        assert!(ticks.len() <= 6 && ticks.first() == Some(&lo));
    }

    #[test]
    fn ticks_and_margins_read_as_written() {
        assert_eq!(mb_tick(5000.0), "5 GB");
        assert_eq!(mb_tick(500.0), "500 MB");
        assert_eq!(sec_tick(0.25), "0.25 s");
        assert_eq!(sec_tick(2.0), "2 s");
        assert_eq!(plus_minus(Some(0.021)).as_deref(), Some("±2.1"));
        assert_eq!(plus_minus(Some(0.12)).as_deref(), Some("±12"));
    }

    #[test]
    fn labels_keep_inside_the_plot() {
        let p = |id: &str, x: f64, y: f64| ChartPoint {
            id: id.into(),
            name: id.into(),
            family: id.into(),
            label: id.into(),
            variant: None,
            series: Series::Paddle,
            x,
            y,
            hollow: false,
            rows: vec![],
        };
        let points = vec![p("a", 1.0, 90.0), p("b", 2.0, 91.0)];
        let pos = vec![(300.0, 200.0), (320.0, 195.0)];
        let bounds = Rect { x1: 46.0, y1: 48.0, x2: 756.0, y2: 364.0 };
        let placed = place_labels(&points, &pos, &[], bounds);
        assert_eq!(placed.len(), 2);
        for l in placed {
            assert!(l.rect.x1 >= bounds.x1 && l.rect.x2 <= bounds.x2 && l.rect.y1 >= bounds.y1 && l.rect.y2 <= bounds.y2);
        }
    }
}

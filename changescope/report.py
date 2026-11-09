"""PDFレポート（影響分析・変更案の比較）。分析結果を、上司や関係部門に渡せる形で持ち帰るためのもの。

アップロードしたデータや画面で作ったデータはサーバーに保存しないため、結果はPDFで持ち帰ってもらう。
日本語を正しく表示するため、日本語フォント（BIZ UDPゴシック、SIL Open Font License）を assets/fonts に同梱している。
PDFには使った文字だけを埋め込むので、ファイルは小さく済む。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import networkx as nx
from fpdf import FPDF
from fpdf.enums import WrapMode

from changescope import models
from changescope.assessment import METRIC_DEFINITIONS, UNCERTAIN_ZERO_NOTE, Assessment
from changescope.compare import Comparison, Split
from changescope.gaps import Finding
from changescope.graph_engine import ImpactItem, ImpactResult, describe_path
from changescope.insights import department_of
from changescope.next_actions import Action, UncertainLink
from changescope.oversight import OversightReport
from changescope.stakeholders import Stakeholder
from changescope.theme import THEME, rgb

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
FONT = "bizud"
# 色はテーマ（changescope/theme.py）に合わせる。画面とPDFの印象をそろえるため
NAVY, GOLD, INK, SUB, LINE, CREAM = (rgb(THEME.dark), rgb(THEME.accent), rgb(THEME.ink), rgb(THEME.sub),
                                     rgb(THEME.line), rgb(THEME.cream))
STATUS = {"confirmed": "確認済", "assumed": "推定", "unconfirmed": "未確認"}
SOURCE = {"sample": "架空サンプルデータ（サンプル商事株式会社）", "upload": "アップロードしたデータ",
          "diagram": "画面で作成・編集したデータ"}
MAX_ROWS = 60  # 1つの表に載せる最大の行数（多すぎると読めないため。超えた分は件数だけ書く）


class ReportPDF(FPDF):
    """紺と金の差し色の、日本語のレポート。"""

    def __init__(self, title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.report_title = title
        self.add_font(FONT, "", str(FONT_DIR / "BIZUDPGothic-Regular.ttf"))
        self.add_font(FONT, "B", str(FONT_DIR / "BIZUDPGothic-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(16, 16, 16)
        self.set_title(title)
        self.set_creator("ChangeScope AI")

    def header(self) -> None:
        if self.page_no() == 1:
            return
        self.set_font(FONT, "", 8)
        self.set_text_color(*SUB)
        self.cell(0, 6, f"ChangeScope AI　{self.report_title}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*GOLD)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(3)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font(FONT, "", 8)
        self.set_text_color(*SUB)
        self.cell(0, 6, f"{self.page_no()} / {{nb}}", align="C")

    # ---------- 部品 ----------
    def cover(self, subtitle: str, meta: list[tuple[str, str]]) -> None:
        self.add_page()
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 42, style="F")
        self.set_fill_color(*GOLD)
        self.rect(0, 42, self.w, 1.6, style="F")
        self.set_xy(self.l_margin, 12)
        self.set_text_color(*GOLD)
        self.set_font(FONT, "", 9)
        self.cell(0, 5, "CHANGESCOPE AI", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(255, 255, 255)
        self.set_font(FONT, "B", 20)
        self.cell(0, 11, self.report_title, new_x="LMARGIN", new_y="NEXT")
        self.set_font(FONT, "", 9.5)
        self.cell(0, 6, subtitle, new_x="LMARGIN", new_y="NEXT")
        self.set_y(52)
        self.key_values(meta)

    def section(self, title: str) -> None:
        if self.get_y() > self.h - 70:  # 見出しだけがページの下に残らないように
            self.add_page()
        self.ln(4)
        self.set_text_color(*NAVY)
        self.set_font(FONT, "B", 13)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*GOLD)
        self.set_line_width(0.6)
        self.line(self.l_margin, self.get_y(), self.l_margin + 30, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)

    def subheading(self, text: str) -> None:
        self.set_text_color(*NAVY)
        self.set_font(FONT, "B", 10.5)
        self.multi_cell(0, 6, text, wrapmode=WrapMode.CHAR, new_x="LMARGIN", new_y="NEXT")

    def paragraph(self, text: str, size: float = 9.5, color=INK) -> None:
        self.set_text_color(*color)
        self.set_font(FONT, "", size)
        self.multi_cell(0, 5.6, text, wrapmode=WrapMode.CHAR, new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

    def bullets(self, items: list[str]) -> None:
        for item in items:
            self.paragraph(f"・{item}")

    def note(self, text: str) -> None:
        """金の縦線つきの注記（サンプルやAIの推測であることの表示などに使う）。"""
        self.set_font(FONT, "", 9)
        self.set_text_color(*INK)
        self.set_fill_color(*CREAM)
        top = self.get_y()
        self.set_x(self.l_margin + 3)
        self.multi_cell(self.w - self.l_margin - self.r_margin - 3, 5.4, text, fill=True, wrapmode=WrapMode.CHAR,
                        new_x="LMARGIN", new_y="NEXT", padding=(2, 3, 2, 3))
        self.set_fill_color(*GOLD)
        self.rect(self.l_margin, top, 1.6, self.get_y() - top, style="F")
        self.ln(2)

    def key_values(self, rows: list[tuple[str, str]]) -> None:
        self.table([("項目", "内容")], rows, (30, 70), header=False)

    def table(self, headers: list[tuple[str, ...]] | tuple, rows: list[tuple], widths: tuple, header: bool = True,
              size: float = 8.5) -> None:
        """表。headers は見出しの行（1行）。行が多すぎるときは、先頭だけ載せて件数を書く。"""
        shown = rows[:MAX_ROWS]
        self.set_font(FONT, "", size)
        self.set_text_color(*INK)
        self.set_draw_color(*LINE)
        # 1行おきの塗りは、そのときの塗りの色を使うため、薄いクリーム色にしておく（金の帯の色が残らないように）
        self.set_fill_color(*CREAM)
        heading = {"fill_color": NAVY, "color": (255, 255, 255)}
        with FPDF.table(self, col_widths=widths, wrapmode=WrapMode.CHAR, line_height=4.8, padding=1.6,
                        first_row_as_headings=header, headings_style=_style(heading) if header else None,
                        borders_layout="HORIZONTAL_LINES" if header else "NONE",
                        cell_fill_color=(250, 247, 240), cell_fill_mode="ROWS", text_align="LEFT") as table:
            if header:
                row = table.row()
                for text in headers[0]:
                    row.cell(text)
            for values in shown:
                row = table.row()
                for value in values:
                    row.cell(_text(value))
        if len(rows) > MAX_ROWS:
            self.paragraph(f"ほか {len(rows) - MAX_ROWS} 行（画面で確認できます）", size=8.5, color=SUB)
        self.ln(2)


def _style(options: dict):
    from fpdf.fonts import FontFace
    return FontFace(family=FONT, emphasis="BOLD", color=options["color"], fill_color=options["fill_color"])


def _text(value) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(str(v) for v in value) or "なし"
    return "" if value is None else str(value)


def _output(pdf: ReportPDF) -> bytes:
    pdf.alias_nb_pages()
    return bytes(pdf.output())


def _now() -> str:
    return datetime.now().strftime("%Y年%m月%d日 %H:%M")


# ---------- 影響分析のレポート ----------
def analysis_report(graph: nx.MultiDiGraph, source: str, change_text: str, result: ImpactResult,
                    assessment: Assessment | None, actions: list[Action], stakeholders: list[Stakeholder],
                    links: list[UncertainLink], hidden: list[ImpactItem], gaps: list[Finding],
                    oversight: dict | None = None, max_depth: int | None = None) -> bytes:
    """影響分析の結果をPDFにする。oversight は AIの確認漏れの結果（{"kind": "sample"/"ai", "report": ..., "label": ...}）。"""
    pdf = ReportPDF("影響分析レポート")
    name = lambda element_id: graph.nodes[element_id]["name"]  # noqa: E731
    pdf.cover("変更の前に、まだ確認していないことを見つける", [
        ("作成日時", _now()),
        ("データ", SOURCE.get(source, source)),
        ("変更内容", change_text or "（入力なし）"),
        ("変更対象", "、".join(name(t) for t in result.targets)),
        ("影響の件数", f"変更対象 {len(result.targets)}件／影響先 {len(result.impacts)}件（直接 {len(result.direct)}件・間接 {len(result.indirect)}件）"
                     + (f"（{max_depth}段先までたどった）" if max_depth else "")),
    ])
    if source == "sample":
        pdf.note("このレポートは、架空の会社（サンプル商事株式会社）のサンプルデータを分析したものです。")

    if assessment is not None:
        pdf.section("1. 結論")
        pdf.subheading(f"影響の広さ：{assessment.level}　{assessment.headline}")
        pdf.paragraph("影響の広さは関係する部門の数による指標で、リスクの大小を示すものではありません。", size=8.5, color=SUB)
        pdf.paragraph(assessment.meaning)
        pdf.paragraph(f"まずやること：{assessment.first_step}")
        if assessment.caution:
            pdf.note(assessment.caution)
        if assessment.stance:
            pdf.paragraph("意識すること", color=NAVY)
            pdf.bullets(assessment.stance)
        if assessment.basis:
            pdf.paragraph(assessment.basis, size=8.5, color=SUB)  # 「判定の根拠：」から始まる文

    pdf.section("2. 実際の案件での対応手順")
    pdf.paragraph("実務でこの結果を使う場合の対応例です。", size=8.5, color=SUB)
    for n, action in enumerate(actions, start=1):
        pdf.subheading(f"{n}. {action.title}")
        pdf.paragraph(action.detail)
        items = [f"{l.text}　→ 確認先：{'、'.join(l.contacts) or '責任部門が未登録'}" for l in action.links]
        pdf.bullets(items + list(action.items))

    pdf.section("3. 誰に影響するか")
    pdf.table([("関係者", "種類", "所属", "確認状態", "影響する理由")],
              [(s.name, s.type_label, s.department, STATUS.get(s.status, s.status),
                [f"{r.text}（{STATUS.get(r.status, r.status)}）" for r in s.reasons]) for s in stakeholders],
              (24, 18, 18, 14, 66))

    pdf.section("4. 要確認のつながり")
    if links:
        pdf.paragraph("推定・未確認のつながりです。1本のつながりが未確認だと、その先の影響もすべて要確認になります。"
                      "確かめると分かることが多い順に並べています。")
        pdf.table([("確かめるつながり", "状態", "確認先", "有無がはっきりする影響", "根拠")],
                  [(l.text, STATUS.get(l.status, l.status), "、".join(l.contacts) or "責任部門が未登録",
                    [f"{l.affected}件："] + l.affected_names, l.evidence) for l in links],
                  (40, 12, 24, 40, 24))
    else:
        pdf.paragraph("登録済みのつながりの範囲では、確かめる必要があるつながりはありません（経路のつながりはすべて確認済みです）。"
                      "登録していないつながり、たどった段数より先、情報が古くなったつながりは含まれません。")

    pdf.section("5. 見落としやすい影響")
    pdf.paragraph("変更対象の責任部門とは別の部門に、2段以上先で伝わる影響です。")
    if hidden:
        pdf.table([("影響を受ける要素", "所属部門", "影響の経路")],
                  [(i.name, _department(graph, i.element_id), describe_path(graph, i)) for i in hidden], (34, 24, 82))
    else:
        pdf.paragraph("見落としやすい影響はありません。")

    pdf.section("6. 見落としチェック")
    for finding in gaps:
        pdf.subheading(f"【{finding.kind}】{finding.title}")
        pdf.paragraph(finding.detail)
        if finding.items:
            pdf.paragraph("対象：" + "、".join(finding.items), size=8.5, color=SUB)
    if not gaps:
        pdf.paragraph("見落としチェックで指摘する項目はありません。")

    number = 7
    if oversight:
        _oversight_section(pdf, oversight)
        number = 8

    pdf.section(f"{number}. 影響を受ける要素の一覧（影響の大きい順）")
    pdf.table([("影響度", "要素", "種類", "所属部門", "区分", "確認状態", "影響の経路")],
              [(i.score, i.name, models.element_type_label(i.element_type), _department(graph, i.element_id),
                f"{'直接' if i.level == 'direct' else '間接'}（{i.depth}段）", STATUS.get(i.path_status, i.path_status),
                describe_path(graph, i)) for i in result.impacts],
              (11, 24, 16, 16, 14, 12, 47))
    return _output(pdf)


def _department(graph: nx.MultiDiGraph, element_id: str) -> str:
    department = department_of(graph, element_id)
    return graph.nodes[department]["name"] if department else ""


def _oversight_section(pdf: ReportPDF, oversight: dict) -> None:
    report: OversightReport = oversight["report"]
    pdf.section("7. AIで調べた確認漏れ")
    pdf.note(oversight["label"] + "　AIは組織全体を知りません。区分の「登録済みのつながり」は登録されたつながりを根拠にした指摘"
             "（番号は照合済み、内容の正しさは未確認）、「一般的な確認の観点」は変更の種類から一般的に確認すべきこと、"
             "「AIの推測」は登録されていないものの推測です。どれも確認先に聞いて確かめてください。")
    pdf.table([("重要度", "観点", "確認していないこと", "確認先と質問", "区分")],
              [(f.importance, f.viewpoint, f"{f.title}\n{f.detail}",
                f"{f.contact}{'' if f.contact_registered else '（未登録の部門候補）'}\n質問：{f.question}", f.basis)
               for f in report.findings],
              (11, 15, 50, 50, 14))
    if report.department_points:
        pdf.subheading("部門別の調整ポイント")
        pdf.table([("部門・担当", "調整ポイント")],
                  [(d["department"], [f"・{p['viewpoint']}：{p['content']}" for p in d["points"]])
                   for d in report.department_points], (30, 110))
    if report.risks:
        pdf.subheading("トラブルの予測")
        pdf.table([("起こりうるトラブル", "起きる条件", "影響が広がる先", "予防策")],
                  [(r["scenario"], r["condition"], r["spread_to"], r["prevention"]) for r in report.risks],
                  (38, 34, 34, 34))
    if report.hidden_costs:
        pdf.subheading("見落としがちな費用（金額はAIに作らせていません。要見積もり）")
        pdf.table([("費用の項目", "見落としやすい理由")], [(c["item"], c["detail"]) for c in report.hidden_costs], (40, 100))
    if report.approach:
        pdf.subheading("推奨する進め方")
        pdf.table([("段階", "内容")], [(a["step"], a["detail"]) for a in report.approach], (40, 100))
    if report.unregistered:
        pdf.subheading("未登録の影響の推測（AIの推測）")
        pdf.table([("要素の候補", "種類", "理由")],
                  [(u["name"], u["element_type"], u["reason"]) for u in report.unregistered], (40, 24, 76))


# ---------- 変更案の比較のレポート ----------
def comparison_report(comparison: Comparison, titles: dict[str, str], source: str) -> bytes:
    """変更案A・Bの比較をPDFにする。titles は表の見出し（例：{"a": "A案（システムを入れ替える）", ...}）。

    画面と同じ順・同じ内容にする（要約 → 重要な違い → 確認事項 → 比較表 → 定義と範囲 → 差分）。AIは使っていない。
    """
    pdf = ReportPDF("変更案の比較レポート")
    a, b = comparison.a, comparison.b
    goal = comparison.goal
    pdf.cover("共通の目的に対する、2つの変更案の対応範囲と確認事項の違い", [
        ("作成日時", _now()),
        ("データ", SOURCE.get(source, source)),
        ("目的", goal.purpose or "未入力（目的への適合性は未評価）"),
        ("成功条件", goal.success or "未入力"),
        (titles["a"], f"{a.option.text}（変更対象：{len(a.option.targets)}件）"),
        (titles["b"], f"{b.option.text}（変更対象：{len(b.option.targets)}件）"),
    ])
    pdf.note("このレポートは、どちらの案が良いかを決めるものではありません。影響範囲が狭い案が、目的を満たすとは限らないためです。"
             "費用・期間は、入力がなければ「未入力・要見積もり」と表示しています（このツールでは計算しません）。"
             "このレポートの内容はAIを使わず、登録データの分析結果と入力された内容から作っています。")
    if source == "sample":
        pdf.note("架空の会社（サンプル商事株式会社）のサンプルデータと、架空の目的・成功条件を使っています。")

    pdf.section("1. 共通の目的と、判断を分けるポイント")
    pdf.paragraph(f"目的：{goal.purpose or '未入力'}　／　成功条件：{goal.success or '未入力'}")
    for line in comparison.summary:
        pdf.paragraph(line)

    pdf.section("2. 各案の概要")
    pdf.table([("項目", titles["a"], titles["b"])],
              [(label, lines_a, lines_b) for (label, lines_a), (_, lines_b) in zip(comparison.cards["a"], comparison.cards["b"])],
              (28, 56, 56))

    pdf.section("3. 重要な違い")
    pdf.table([("観点", titles["a"], titles["b"])],
              [(r.viewpoint, r.a, r.b) for r in comparison.differences], (32, 54, 54))

    pdf.section("4. 判断前に確認すること")
    pdf.table([("区分", "確認事項", "なぜ判断に必要か", "確認先", "対象案", "確認の根拠")],
              [(c.kind, c.item, c.why, c.contact, c.target, c.basis) for c in comparison.checks],
              (14, 41, 32, 20, 11, 22))

    pdf.section("5. 比較表")
    pdf.paragraph(f"{comparison.max_depth}段先までたどった結果です。件数の差は違いを示すだけで、少ない案が優れているという意味ではありません。")
    pdf.table([("観点", titles["a"], titles["b"], "違い")],
              [(r.viewpoint, r.a, r.b, r.difference) for r in comparison.rows], (28, 44, 44, 24))

    pdf.section("6. 分析条件と、分かる範囲")
    pdf.paragraph(f"分析条件：変更対象から{comparison.max_depth}段先まで、登録されたつながりの向きにたどっています。")
    pdf.table([("指標", "定義")], METRIC_DEFINITIONS, (40, 100))
    pdf.subheading("登録データで分かること")
    pdf.bullets(["登録されたつながりをたどって届く、影響先・部門・関係者", "登録された関係のうち、確認状態が推定・未確認のもの"])
    pdf.subheading("未評価の事項")
    pdf.bullets(["目的への適合性と、期待する効果（入力された内容は、入力された見込みです）",
                 "業務の重要度、停止時の損失などのリスクの大きさ（影響の広さは、リスクの大小を示しません）",
                 "費用と期間（入力された値は、ユーザー申告です）",
                 f"未登録の関係や、分析範囲外の影響（{UNCERTAIN_ZERO_NOTE}）"])

    for number, (title, split, caption) in enumerate([
        ("要確認のつながり", comparison.uncertain, "確かめないと、影響があるかどうかがはっきりしないつながりです。"),
        ("関係する部門・担当", comparison.stakeholders, ""),
        ("見落としやすい影響", comparison.hidden, "変更対象の責任部門とは別の部門に、2段以上先で伝わる影響です。"),
        ("確認すべき観点", comparison.gaps, "データ移行・連携・規程・切り戻しなど、変更時に忘れやすい確認事項です。"),
        ("変更対象と影響先", comparison.elements, "「だけ」は、今回の登録データと分析条件で、その案にのみ影響候補として抽出されたものです。もう一方の案で対応が不要になるという意味ではありません。"),
    ], start=7):
        pdf.section(f"{number}. {title}（Aだけ・Bだけ・両方）")
        if caption:
            pdf.paragraph(caption)
        _split_table(pdf, split, titles)
    return _output(pdf)


def _split_table(pdf: ReportPDF, split: Split, titles: dict[str, str]) -> None:
    pdf.table([(f"{titles['a']}だけ（{len(split.only_a)}）", f"{titles['b']}だけ（{len(split.only_b)}）",
                f"両方（{len(split.both)}）")],
              [(split.only_a or ["なし"], split.only_b or ["なし"], split.both or ["なし"])], (47, 47, 46))

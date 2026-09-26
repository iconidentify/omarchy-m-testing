module ApplicationHelper
  def nav_link(label, path)
    current = current_page?(path) || (path != root_path && request.path.start_with?(path))
    link_to label, path, class: ("current" if current), "aria-current": ("page" if current)
  end

  # A terminal card: a bordered box with its title set into the top border.
  def card(title = nil, klass: nil, id: nil, &block)
    tag.section(class: [ "card", klass ].compact.join(" "), id:) do
      safe_join([ (tag.h2(title, class: "card-title") if title), capture(&block) ].compact)
    end
  end

  def state_badge(state, label: ResultState.words(state))
    tag.span(label, class: "badge badge-#{state}")
  end

  def outcome_badge(outcome)
    tag.span(Catalogue.outcome_words(outcome), class: "badge badge-#{ResultState.for_outcome(outcome)} outcome outcome-#{outcome}")
  end

  # One matrix cell: a coloured square once machines agree, an outlined hint while unconfirmed.
  def matrix_cell(cell, feature_id:, link: nil)
    glyph = ResultState.glyph(cell.display_state)
    content = link && cell.reports.any? ? link_to(glyph, link, "aria-label": cell.summary) : glyph
    tag.td(content, class: cell.css_class, title: cell.summary, data: { feature: feature_id, state: cell.state || "unconfirmed" })
  end

  # A catalogue state ("upstream 6.2", "linux-asahi", "supported 7.1.12") for one layer.
  def expected_words(state)
    return "–" if state.nil?

    [ state["status"], state["version"] ].compact.join(" ")
  end

  def expected_class(layer, state)
    status = state&.fetch("status", nil)
    good = case layer
    when "asahi" then Catalogue::ASAHI_SUPPORTED.include?(status)
    else %w[supported asahi].include?(status)
    end
    return "expected expected-none" if status.nil? || status == "absent"

    good ? "expected expected-yes" : "expected expected-no"
  end

  def uploaded_at(report) = report.created_at.utc.strftime("%Y-%m-%d %H:%M UTC")

  def check_section(check_id) = check_id.split(".").first
end

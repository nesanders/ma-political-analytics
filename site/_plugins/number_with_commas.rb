# Liquid ships no thousands-separator filter (that's a Rails/ActionView
# helper, not stock Liquid) — this site's own `jekyll build` isn't run
# through GitHub Pages' restricted plugin whitelist (deploy.yml drives
# bundler/jekyll directly), so a small custom filter is the simplest fix
# rather than hand-rolling comma-grouping in Liquid string filters.
module Jekyll
  module NumberFilters
    # `{{ value | round: 0 | number_with_commas }}` — round first, since
    # this only groups the integer part and drops nothing after the
    # decimal point itself.
    def number_with_commas(number)
      return number if number.nil?
      number.to_i.to_s.reverse.gsub(/(\d{3})(?=\d)/, '\1,').reverse
    end
  end
end

Liquid::Template.register_filter(Jekyll::NumberFilters)

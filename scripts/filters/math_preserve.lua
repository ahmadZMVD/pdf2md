-- AST-level math preservation for GitHub Flavored Markdown output.
--
-- Pandoc's GFM writer renders TeX math as inline code spans (`` $x^2$ ``)
-- or fenced ```math blocks, and string-level post-processing destroys
-- real inline code containing dollar signs (e.g. `` `$PATH` ``). This filter
-- operates exclusively on the Math AST element:
--
--   * Inline math is rewritten to $...$ and display math to $$...$$.
--   * Code, CodeBlock, and plain-text elements (including currency) are
--     never inspected or rewritten.
--   * Fenced blocks whose info string is exactly "math" are user
--     documentation, not mathematics, and pass through untouched.
--
-- The filter is bundled with the application and invoked via
-- ``pandoc --lua-filter=math_preserve.lua``.

function Math(element)
  local delimiter = element.mathtype == "DisplayMath" and "$$" or "$"
  return pandoc.RawInline("markdown", delimiter .. element.text .. delimiter)
end

return {
  { Math = Math },
}

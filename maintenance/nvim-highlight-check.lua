-- Highlight gate run by ansible/tasks/verify.yml and tests/container-smoke.sh:
--   nvim --headless -i NONE <file> "+luafile maintenance/nvim-highlight-check.lua" +qa
-- Fails (exit 1) unless the opened file has a treesitter highlighter attached
-- and its highlights queries, injections included, run over the whole buffer
-- without a Lua error or an E5108/decoration-provider message. A headless
-- load alone never attaches a highlighter, so it cannot catch a parser or
-- query that breaks on the installed Neovim.

local buf = vim.api.nvim_get_current_buf()

local ok, err = pcall(function()
  local parser = assert(vim.treesitter.get_parser(buf), "no treesitter parser for the buffer")
  parser:parse(true)
  assert(vim.treesitter.highlighter.active[buf], "no treesitter highlighter is attached")
  parser:for_each_tree(function(tree, ltree)
    local query = vim.treesitter.query.get(ltree:lang(), "highlights")
    if query then
      for _ in query:iter_captures(tree:root(), buf) do
      end
    end
  end)
  vim.cmd("redraw!")
end)

local messages = vim.api.nvim_exec2("messages", { output = true }).output
if ok and (messages:find("E5108", 1, true) or messages:find("Decoration provider", 1, true)) then
  ok, err = false, messages
end
if ok and vim.v.errmsg ~= "" then
  ok, err = false, vim.v.errmsg
end

if not ok then
  io.stderr:write(vim.api.nvim_buf_get_name(buf) .. ": " .. tostring(err) .. "\n")
  vim.cmd("cquit 1")
end

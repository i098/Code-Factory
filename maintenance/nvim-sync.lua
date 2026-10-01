-- Headless refresh run by ansible/tasks/editor.yml:
--   nvim --headless "+luafile maintenance/nvim-sync.lua" +cquit
-- Moves every lazy.nvim plugin to its latest commit and installs every
-- treesitter parser the config lists at the revision nvim-treesitter's own
-- lockfile names. Prints "nvim-sync: changed" when a parser changed; plugin
-- commits that moved upstream are recorded in lazy-lock.json but are not a
-- change. Exits non-zero (through the trailing +cquit) on any failure.

local function state()
  local files = vim.fn.glob(vim.fn.stdpath("data") .. "/lazy/nvim-treesitter/parser-info/*", false, true)
  local parts = {}
  for _, file in ipairs(files) do
    table.insert(parts, file .. "\n" .. table.concat(vim.fn.readfile(file, "b"), "\n"))
  end
  return table.concat(parts, "\n")
end

local before = state()

vim.cmd("Lazy! sync")
for name, plugin in pairs(require("lazy.core.config").plugins) do
  assert(not require("lazy.core.plugin").has_errors(plugin), "lazy.nvim failed to sync " .. name)
end

-- Loading nvim-treesitter runs the config's setup, which installs missing
-- parsers asynchronously, and lazy's :TSUpdate build may still be running.
-- Let those jobs finish first so no parser is built twice at once.
local configs = require("nvim-treesitter.configs")
local idle = 0
vim.wait(900000, function()
  idle = #vim.api.nvim_get_proc_children(vim.fn.getpid()) == 0 and idle + 1 or 0
  return idle >= 5
end, 200)

local wanted = configs.get_ensure_installed_parsers()
require("nvim-treesitter.install").update({ with_sync = true })(unpack(wanted))
local parser_dir = configs.get_parser_install_dir()
for _, lang in ipairs(wanted) do
  assert(vim.uv.fs_stat(parser_dir .. "/" .. lang .. ".so"), "treesitter parser " .. lang .. " is not installed")
end

if state() ~= before then
  io.stdout:write("\nnvim-sync: changed\n")
end
vim.cmd("qall!")

-- ============================================================
-- Basic options
-- ============================================================
vim.g.mapleader = " "
vim.g.maplocalleader = " "

vim.opt.termguicolors = true -- 24-bit color (needed for themes)
vim.opt.number = true
vim.opt.relativenumber = true
vim.opt.cursorline = true
vim.opt.signcolumn = "yes"
vim.opt.showmode = false -- statusline shows it instead
vim.opt.laststatus = 3 -- one global statusline
vim.opt.scrolloff = 6
vim.opt.wrap = false
vim.opt.expandtab = true
vim.opt.shiftwidth = 2
vim.opt.tabstop = 2
vim.opt.smartindent = true
vim.opt.ignorecase = true
vim.opt.smartcase = true
vim.opt.splitright = true
vim.opt.splitbelow = true
vim.opt.updatetime = 250
vim.opt.undofile = true
vim.opt.fillchars = { eob = " " }

-- Terminal has no Nerd Font, so every plugin below stays on plain text glyphs.
local HAS_NERD_FONT = false

-- ============================================================
-- lazy.nvim bootstrap
-- ============================================================
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.uv.fs_stat(lazypath) then
  vim.fn.system({
    "git",
    "clone",
    "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git",
    "--branch=stable",
    lazypath,
  })
end
vim.opt.rtp:prepend(lazypath)

require("lazy").setup({
  -- ----------------------------------------------------------
  -- Colorscheme
  -- ----------------------------------------------------------
  {
    "catppuccin/nvim",
    name = "catppuccin",
    lazy = false,
    priority = 1000,
    config = function()
      require("catppuccin").setup({
        flavour = "mocha",
        transparent_background = false,
        term_colors = true,
        styles = {
          comments = { "italic" },
          conditionals = { "italic" },
          keywords = { "bold" },
          functions = { "bold" },
          types = { "italic" },
        },
        integrations = {
          alpha = true,
          gitsigns = true,
          treesitter = true,
          indent_blankline = { enabled = true, colored_indent_levels = true },
          native_lsp = { enabled = true },
        },
      })
      vim.cmd.colorscheme("catppuccin")
    end,
  },

  -- ----------------------------------------------------------
  -- Real syntax highlighting
  -- ----------------------------------------------------------
  {
    "nvim-treesitter/nvim-treesitter",
    branch = "main",
    lazy = false,
    build = ":TSUpdate",
    opts = {
      ensure_installed = {
        "bash",
        "c",
        "css",
        "diff",
        "dockerfile",
        "git_config",
        "gitcommit",
        "go",
        "html",
        "javascript",
        "json",
        "lua",
        "luadoc",
        "make",
        "markdown",
        "markdown_inline",
        "python",
        "query",
        "regex",
        "rust",
        "sql",
        "toml",
        "tsx",
        "typescript",
        "vim",
        "vimdoc",
        "yaml",
      },
    },
    config = function(_, opts)
      require("nvim-treesitter").install(opts.ensure_installed)
      vim.api.nvim_create_autocmd("FileType", {
        callback = function()
          if pcall(vim.treesitter.start) then
            vim.bo.indentexpr = "v:lua.require'nvim-treesitter'.indentexpr()"
          end
        end,
      })
    end,
  },

  -- ----------------------------------------------------------
  -- Statusline
  -- ----------------------------------------------------------
  {
    "nvim-lualine/lualine.nvim",
    event = "VeryLazy",
    opts = {
      options = {
        theme = "catppuccin-mocha",
        icons_enabled = HAS_NERD_FONT,
        component_separators = { left = "|", right = "|" },
        section_separators = { left = "", right = "" },
        globalstatus = true,
      },
      sections = {
        lualine_a = { "mode" },
        lualine_b = { "branch", { "diff", symbols = { added = "+", modified = "~", removed = "-" } } },
        lualine_c = { { "filename", path = 1 } },
        lualine_x = {
          { "diagnostics", symbols = { error = "E", warn = "W", info = "I", hint = "H" } },
          "encoding",
          "filetype",
        },
        lualine_y = { "progress" },
        lualine_z = { "location" },
      },
    },
  },

  -- ----------------------------------------------------------
  -- Git signs in the gutter
  -- ----------------------------------------------------------
  {
    "lewis6991/gitsigns.nvim",
    event = { "BufReadPre", "BufNewFile" },
    opts = {
      signs = {
        add = { text = "+" },
        change = { text = "~" },
        delete = { text = "_" },
        topdelete = { text = "-" },
        changedelete = { text = "~" },
      },
      current_line_blame = false,
    },
  },

  -- ----------------------------------------------------------
  -- Indent guides
  -- ----------------------------------------------------------
  {
    "lukas-reineke/indent-blankline.nvim",
    main = "ibl",
    event = { "BufReadPost", "BufNewFile" },
    opts = {
      indent = { char = "|" },
      scope = { enabled = true, show_start = false, show_end = false },
      exclude = { filetypes = { "alpha", "help", "lazy", "checkhealth" } },
    },
  },

  -- ----------------------------------------------------------
  -- Inline color previews for #rrggbb, rgb(), etc.
  -- ----------------------------------------------------------
  {
    "norcalli/nvim-colorizer.lua",
    event = { "BufReadPost", "BufNewFile" },
    config = function()
      require("colorizer").setup({ "*" }, { css = true, names = false })
    end,
  },

  -- ----------------------------------------------------------
  -- Highlight the other matching bracket / tag
  -- ----------------------------------------------------------
  {
    "andymass/vim-matchup",
    event = { "BufReadPost", "BufNewFile" },
    init = function()
      vim.g.matchup_matchparen_offscreen = { method = "popup" }
    end,
  },

  -- ----------------------------------------------------------
  -- Start screen
  -- ----------------------------------------------------------
  {
    "goolord/alpha-nvim",
    event = "VimEnter",
    config = function()
      local dashboard = require("alpha.themes.dashboard")

      dashboard.section.header.val = {
        [[  ███╗   ██╗███████╗ ██████╗ ██╗   ██╗██╗███╗   ███╗  ]],
        [[  ████╗  ██║██╔════╝██╔═══██╗██║   ██║██║████╗ ████║  ]],
        [[  ██╔██╗ ██║█████╗  ██║   ██║██║   ██║██║██╔████╔██║  ]],
        [[  ██║╚██╗██║██╔══╝  ██║   ██║╚██╗ ██╔╝██║██║╚██╔╝██║  ]],
        [[  ██║ ╚████║███████╗╚██████╔╝ ╚████╔╝ ██║██║ ╚═╝ ██║  ]],
        [[  ╚═╝  ╚═══╝╚══════╝ ╚═════╝   ╚═══╝  ╚═╝╚═╝     ╚═╝  ]],
      }
      dashboard.section.header.opts.hl = "AlphaHeader"

      local buttons = {
        dashboard.button("e", "Open Yazi", "<cmd>Yazi<CR>"),
        dashboard.button("f", "Find files", "<cmd>Yazi cwd<CR>"),
        dashboard.button("r", "Recent files", "<cmd>browse oldfiles<CR>"),
        dashboard.button("n", "New file", "<cmd>ene<CR>"),
        dashboard.button("q", "Quit", "<cmd>qa<CR>"),
      }
      for _, button in ipairs(buttons) do
        button.opts.cursor = 0
        button.opts.hl = "AlphaButton"
        button.opts.hl_shortcut = "AlphaShortcut"
      end
      dashboard.section.buttons.val = buttons

      dashboard.section.footer.val = { "neovim " .. tostring(vim.version()) }
      dashboard.section.footer.opts.hl = "AlphaFooter"

      dashboard.config.layout = {
        { type = "padding", val = 1 },
        dashboard.section.header,
        { type = "padding", val = 2 },
        dashboard.section.buttons,
        { type = "padding", val = 1 },
        dashboard.section.footer,
      }
      dashboard.opts.opts = { margin = 0 }

      require("alpha").setup(dashboard.config)

      -- Vertically center the dashboard: header 6 + pad 2 + buttons (2n-1) + pad 1 + footer 1.
      local body = 6 + 2 + (2 * #buttons - 1) + 1 + 1
      local function center()
        if vim.bo.filetype ~= "alpha" then
          return
        end
        local height = vim.api.nvim_win_get_height(0)
        dashboard.config.layout[1].val = math.max(0, math.floor((height - body) / 2))
        pcall(vim.cmd, "AlphaRedraw")
      end

      vim.api.nvim_create_autocmd("VimResized", { pattern = "*", callback = function() vim.schedule(center) end })
      -- alpha itself loads on VimEnter, so that event is already spent here.
      vim.schedule(center)
    end,
  },

  -- ----------------------------------------------------------
  -- File manager
  -- ----------------------------------------------------------
  {
    "mikavilpas/yazi.nvim",
    version = "*",
    event = "VeryLazy",
    dependencies = {
      { "nvim-lua/plenary.nvim", lazy = true },
    },
    keys = {
      {
        "<leader>e",
        "<cmd>Yazi<cr>",
        mode = { "n", "v" },
        desc = "Open Yazi file manager",
      },
    },
    opts = {
      open_for_directories = true,
      floating_window_scaling_factor = 1.0,
      keymaps = {
        show_help = "<f1>",
      },
    },
    init = function()
      vim.g.loaded_netrwPlugin = 1
    end,
  },
}, {
  ui = { icons = HAS_NERD_FONT and {} or {
    cmd = "cmd",
    config = "cfg",
    event = "evt",
    ft = "ft",
    init = "init",
    keys = "keys",
    plugin = "plug",
    runtime = "rt",
    source = "src",
    start = "start",
    task = "ok",
    lazy = "lazy",
  } },
})

-- ============================================================
-- Extra color accents on top of the theme
-- ============================================================
vim.api.nvim_create_autocmd("ColorScheme", {
  pattern = "*",
  callback = function()
    local C = require("catppuccin.palettes").get_palette("mocha")
    local set = vim.api.nvim_set_hl
    set(0, "AlphaHeader", { fg = C.mauve, bold = true })
    set(0, "AlphaButton", { fg = C.blue })
    set(0, "AlphaShortcut", { fg = C.peach, bold = true })
    set(0, "AlphaFooter", { fg = C.overlay1, italic = true })
    set(0, "CursorLineNr", { fg = C.yellow, bold = true })
    set(0, "LineNr", { fg = C.surface2 })
  end,
})
vim.cmd.doautocmd("ColorScheme")

-- Flash the yanked text so edits are visible.
vim.api.nvim_create_autocmd("TextYankPost", {
  pattern = "*",
  callback = function()
    vim.hl.on_yank({ higroup = "IncSearch", timeout = 200 })
  end,
})

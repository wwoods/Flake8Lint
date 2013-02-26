# -*- coding: utf-8 -*-
import os
import time

import sublime
import sublime_plugin

from flake8_harobed.util import skip_line
from lint import lint, lint_external

settings = sublime.load_settings("Flake8Lint.sublime-settings")
FLAKE_DIR = os.path.dirname(os.path.abspath(__file__))
viewToRegionToErrors = {}

def getMessage(view, line):
    regs = (view.get_regions('flake8_errors')
            + view.get_regions('flake8_warnings'))
    viewStorage = viewToRegionToErrors.get(view.id())
    if viewStorage is None:
        return
    tips = []
    for reg in regs:
        if reg.intersects(line):
            tips.append(
                    viewStorage.get(reg.a, {}).get('error', '(Unrecognized)'))
    return tips


class Flake8LintCommand(sublime_plugin.TextCommand):
    """
    Do flake8 lint on current file.
    """
    FILL_STYLES = {
        'fill': sublime.DRAW_EMPTY,
        'outline': sublime.DRAW_OUTLINED,
        'none': sublime.HIDDEN
    }
    def run(self, edit):
        """
        Run flake8 lint.
        """
        # current file name
        filename = os.path.abspath(self.view.file_name())

        # check if active view contains file
        if not filename:
            return

        # check only Python files
        if not self.view.match_selector(0, 'source.python'):
            return

        # save file if dirty
        if self.view.is_dirty():
            self.view.run_command('save')

        # try to get interpreter
        interpreter = settings.get('python_interpreter', 'auto')

        if not interpreter or interpreter == 'internal':
            # if interpreter is Sublime Text 2 internal python - lint file
            self.errors_list = lint(filename, settings)
        else:
            # else - check interpreter
            if interpreter == 'auto':
                interpreter = 'python'
            elif not os.path.exists(interpreter):
                sublime.error_message(
                    "Python Flake8 Lint error:\n"
                    "python interpreter '%s' is not found" % interpreter
                )

            # TODO: correct linter path handle
            # build linter path for Packages Manager installation
            linter = os.path.join(FLAKE_DIR, 'lint.py')

            # build linter path for installation from git
            if not os.path.exists(linter):
                linter = os.path.join(
                    sublime.packages_path(), 'Flake8Lint', 'lint.py')

            if not os.path.exists(linter):
                sublime.error_message(
                    "Python Flake8 Lint error:\n"
                    "sorry, can't find correct plugin path"
                )

            # and lint file in subprocess
            self.errors_list = lint_external(filename, settings,
                                             interpreter, linter)

        # show errors
        if self.errors_list:
            self.show_errors()

    def show_errors(self):
        """
        Show all errors.
        """
        errors_to_show = []

        # get select and ignore settings
        select = settings.get('select') or []
        ignore = settings.get('ignore') or []

        errors = []
        warnings = []
        viewStorage = viewToRegionToErrors[self.view.id()] = {}

        errors_list_filtered = []
        for e in self.errors_list:
            # get error line
            text_point = self.view.text_point(e[0] - 1, e[1] + 1)
            line_text = self.view.substr(self.view.line(text_point))

            # skip line if 'noqa' defined
            if skip_line(line_text):
                continue

            # parse error line to get error code
            code, _ = e[2].split(' ', 1)

            # check if user has a setting for select only errors to show
            if select and filter(lambda err: not code.startswith(err), select):
                continue

            # check if user has a setting for ignore some errors
            if ignore and filter(lambda err: code.startswith(err), ignore):
                continue

            # build line error message
            error = [e[2], u'{0}: {1}'.format(e[0], line_text)]
            if error not in errors_to_show:
                errors_list_filtered.append(e)
                errors_to_show.append(error)

            if e[1]:
                region = self.view.word(text_point)
            else:
                region = self.view.line(text_point)
            viewStorage[region.a] = { 'error': error[0] }
            # a warning if the code is from pep8, unless the user has specified
            # it as an error.  Everything without a code (just syntax errror?)
            # are always errors
            if ((code.startswith('W') or code.startswith('E'))
                    and code not in settings.get('errors', [])):
                warnings.append(region)
            else:
                errors.append(region)

        mark = 'circle' if settings.get('gutter_marks') else ''
        style = self.FILL_STYLES.get(
                settings.get('highlight_style')) or self.FILL_STYLES['fill']

        if settings.get('highlight'):
            # It may not make much sense, but string is the best coloration,
            # as far as I can tell.
            self.view.add_regions('flake8_errors', errors,
                    "flake8lint.error", mark, style)
            # add_regions called in rapid succession can cause issues.
            time.sleep(0.01)
            self.view.add_regions('flake8_warnings', warnings,
                "flake8lint.warning", mark, style)


        # renew errors list with selected and ignored errors
        self.errors_list = errors_list_filtered

        if settings.get('popup'):
            # view errors window
            self.view.window().show_quick_panel(errors_to_show,
                                                self.error_selected)

        if settings.get('results_pane'):
            resultsPane = self._getResultsPane()
            
            edit = resultsPane.begin_edit()
            try:
                resultsPane.erase(edit, sublime.Region(0, resultsPane.size()))
                problems = sorted(errors + warnings, key = lambda r: r.begin())
                resultsPane.insert(edit, 0, self.view.file_name() + ':')
                resultsPane.insert(edit, resultsPane.size(), '\n')
                resultsPane.insert(edit, resultsPane.size(), '\n')
                for problem in problems:
                    line = self.view.line(problem.begin())
                    lineNumber, col = self.view.rowcol(problem.begin())
                    messages = getMessage(self.view, line)
                    resultsPane.insert(edit, resultsPane.size(), 
                            self._formatMessage(lineNumber, 
                                self.view.substr(line), messages))

                if not problems:
                    resultsPane.insert(edit, resultsPane.size(), 
                        '--    pass    --')
            finally:
                resultsPane.end_edit(edit)


    def _formatMessage(self, lineNumber, line, messages):
        lineNumber += 1

        if len(line) > 80:
            line = line[:77] + '...'
        spacer1 = ' ' * (4 - len(str(lineNumber)))
        spacer2 = ' ' * (81 - len(line))
        
        return '{sp1}{lineNumber}: {text}{sp2}{message}\n'.format(
                lineNumber = lineNumber, text = line, sp1 = spacer1,
                sp2 = spacer2, message = " / ".join(messages))


    def _getResultsPane(self):
        """Returns the results pane; creating one if necessary
        """
        window = sublime.active_window()
        resultsPane = [v for v in window.views() 
            if v.name() == 'Lint Results']
        if resultsPane:
            v = resultsPane[0]
            window.focus_view(v)
            window.focus_view(self.view)
            return resultsPane[0]

        #otherwise, create a new view, and name it 'Lint Results'
        results = self.view.window().new_file()
        results.set_name('Lint Results')
        settings = results.settings()
        settings.set('syntax', os.path.join(
                'Packages', 'Default', 'Find Results.hidden-tmLanguage'))
        settings.set('rulers', [6, 86])

        results.set_scratch(True)
        return results


    def error_selected(self, item_selected):
        """
        Error was selected - go to error.
        """
        if item_selected == -1:
            return

        # reset selection
        selection = self.view.sel()
        selection.clear()

        # get error region
        error = self.errors_list[item_selected]
        region_begin = self.view.text_point(error[0] - 1, error[1])

        # go to error
        selection.add(sublime.Region(region_begin, region_begin))
        self.view.show_at_center(region_begin)


class Flake8LintBackground(sublime_plugin.EventListener):
    """
    Listen to Siblime Text 2 events.
    """
    def on_activated(self, view):
        if settings.get('lint_on_load', True):
            if (view.id() not in viewToRegionToErrors
                    and view.file_name() is not None):
                self._lintOnLoad(view)


    def on_post_save(self, view):
        """
        Do lint on file save if not denied in settings.
        """
        if settings.get('lint_on_save', True):
            view.run_command('flake8_lint')


    def on_selection_modified(self, view):
        message = getMessage(view, view.line(view.sel()[0]))
        if message:
            view.set_status('flake8_tip', ' / '.join(message))
        else:
            view.erase_status('flake8_tip')


    def _lintOnLoad(self, view, isFirst = True):
        if isFirst:
            sublime.set_timeout((lambda: self._lintOnLoad(view, False)), 500)
            return

        if view.is_loading():
            sublime.set_timeout((lambda: self._lintOnLoad(view, False)), 100)
            return
        elif view.window().active_view().id() != view.id():
            # Not active anymore, don't lint it!
            return
        view.run_command("flake8_lint")

# -*- coding: utf-8 -*-

# Copyright (C) 2018 Andy Stewart
#
# Author:     Andy Stewart <lazycat.manatee@gmail.com>
# Maintainer: Andy Stewart <lazycat.manatee@gmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


import math
import time
import webbrowser

import fitz
from core.utils import *
from eaf_pdf_annot import AnnotAction
from eaf_pdf_document import PdfDocument
from eaf_pdf_utils import support_hit_max
from PyQt6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPalette
from PyQt6.QtWidgets import QApplication, QToolTip, QWidget
import os
from pathlib import Path


def set_page_crop_box(page):
    if hasattr(page, "set_cropbox"):
        return page.set_cropbox
    else:
        return page.set_cropbox

class PdfViewerWidget(QWidget):

    translate_double_click_word = pyqtSignal(str)

    def __init__(self, url, background_color, buffer, buffer_id, synctex_info):
        super(PdfViewerWidget, self).__init__()

        self.url = url
        self.config_dir = get_emacs_config_dir()
        self.background_color = background_color
        self.buffer = buffer
        self.buffer_id = buffer_id
        self.user_name = get_emacs_var("user-full-name")

        self.is_button_press = False

        self.synctex_info = synctex_info

        self.installEventFilter(self)
        self.setMouseTracking(True)

        (self.marker_letters,
         self.pdf_dark_mode,
         self.pdf_dark_exclude_image,
         self.pdf_default_zoom,
         self.pdf_zoom_step,
         self.pdf_scroll_ratio,
         self.text_highlight_annot_color,
         self.text_underline_annot_color,
         self.inline_text_annot_color,
         self.inline_text_annot_fontsize) = get_emacs_vars([
             "eaf-marker-letters",
             "eaf-pdf-dark-mode",
             "eaf-pdf-dark-exclude-image",
             "eaf-pdf-default-zoom",
             "eaf-pdf-zoom-step",
             "eaf-pdf-scroll-ratio",
             "eaf-pdf-text-highlight-annot-color",
             "eaf-pdf-text-underline-annot-color",
             "eaf-pdf-inline-text-annot-color",
             "eaf-pdf-inline-text-annot-fontsize"])

        self.theme_mode = get_emacs_theme_mode()
        self.theme_foreground_color = get_emacs_theme_foreground()
        self.theme_background_color = get_emacs_theme_background()

        # Init scale and scale mode.
        self.scale = 1.0
        self.scale_before_presentation = 1.0
        self.read_mode = "fit_to_width"
        self.read_mode_before_presentation = "fit_to_width"

        self.rotation = 0

        # Simple string comparation.
        if (self.pdf_default_zoom != 1.0):
            self.read_mode = "fit_to_customize"
            self.scale = self.pdf_default_zoom
        self.horizontal_offset = 0

        # Undo/redo annot actions
        self.annot_action_sequence = []
        self.annot_action_index = -1

        # mark link
        self.is_mark_link = False

        #jump link
        self.is_jump_link = False
        self.link_page_num = None
        self.link_page_offset_x = None
        self.link_page_offset_y = None
        self.jump_link_key_cache_dict = {}

        # hover link
        self.is_hover_link = False
        self.last_hover_link = None

        #global search text
        self.is_mark_search = False
        self.search_term = ""
        self.last_search_term = ""
        self.search_mode_forward = False
        self.search_mode_backward = False
        self.search_text_offset_list = []
        self.current_search_quads = None
        self.search_text_quads_list = []
        self.search_page_history = set()

        #keyboard text mode
        self.is_keyboard_text_mode = False
        self.is_mark_select_text = False
        self.current_select_text_quads = None
        self.select_text_quads_list = []
        self.select_text_words_list = []
        self.current_page_words = None
        self.current_page_word_position = (0, 0, 0)


        # select text
        self.is_select_mode = False
        self.start_char_rect_index = None
        self.start_char_page_index = None
        self.last_char_rect_index = None
        self.last_char_page_index = None
        self.select_area_annot_quad_cache_dict = {}

        # text annot
        self.is_hover_annot = False
        self.hovered_annot = None
        self.edited_annot_page = (None, None)
        self.moved_annot_page = (None, None)
        # popup text annot
        self.popup_text_annot_timer = QTimer()
        self.popup_text_annot_timer.setInterval(300)
        self.popup_text_annot_timer.setSingleShot(True)
        self.popup_text_annot_timer.timeout.connect(self.handle_popup_text_annot_mode)    # type: ignore
        self.is_popup_text_annot_mode = False
        self.is_popup_text_annot_handler_waiting = False
        self.popup_text_annot_pos = (None, None)
        # inline text annot
        self.inline_text_annot_timer = QTimer()
        self.inline_text_annot_timer.setInterval(300)
        self.inline_text_annot_timer.setSingleShot(True)
        self.inline_text_annot_timer.timeout.connect(self.handle_inline_text_annot_mode)    # type: ignore
        self.is_inline_text_annot_mode = False
        self.is_inline_text_annot_handler_waiting = False
        self.inline_text_annot_pos = (None, None)

        self.is_rect_annot_mode = False
        self.rect_annot_beg_ex = 0
        self.rect_annot_beg_ey = 0

        # move text annot
        self.move_text_annot_timer = QTimer()
        self.move_text_annot_timer.setInterval(300)
        self.move_text_annot_timer.setSingleShot(True)
        self.move_text_annot_timer.timeout.connect(self.handle_move_text_annot_mode)    # type: ignore
        self.is_move_text_annot_mode = False
        self.is_move_text_annot_handler_waiting = False
        self.move_text_annot_pos = (None, None)

        # Init scroll attributes.
        self.scroll_offset = 0
        self.scroll_offset_before_presentation = 0
        self.scroll_ratio = 0.05
        self.scroll_wheel_lasttime = time.time()
        if self.pdf_scroll_ratio != 0.05:
            self.scroll_ratio = self.pdf_scroll_ratio

        # Default presentation mode
        self.presentation_mode = False

        # Padding between pages.
        self.page_padding = 10

        # Fill app background color
        self.fill_background()

        # Init font.
        self.page_annotate_padding_x = 10
        self.page_annotate_padding_y = 10

        self.default_progress_font_size = 24
        # Page cache.
        self.page_cache_pixmap_dict = {}
        self.page_cache_scale = self.scale
        self.page_cache_trans = None
        self.page_cache_context_delay = 1000

        self.last_action_time = 0

        self.is_page_just_changed = False

        self.remember_offset = None

        self.last_hover_annot_id = None

        # Saved positions
        self.saved_pos_sequence = []
        self.saved_pos_index = -1
        self.remember_offset = None

        self.start_page_index = 0
        self.start_page_index_before_presentation = 0
        self.current_page_index = 0
        self.last_page_index = 0

        self.load_document(url)

        # Inverted mode.
        self.inverted_mode = False

        # Inverted mode exclude image. (current exclude image inner implement use PDF Only method)
        self.inverted_image_mode = not self.pdf_dark_exclude_image and self.document.is_pdf

        # synctex init page
        if self.synctex_info.page_num is not None:
            self.jump_to_page(self.synctex_info.page_num)    # type: ignore

    def fill_background(self):
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, self.background_color)
        self.setAutoFillBackground(True)
        self.setPalette(pal)

    def load_document(self, url):
        if self.page_cache_pixmap_dict:
            self.page_cache_pixmap_dict.clear()
            self.document.reset_cache()

        # Load document first.
        try:
            self.document = PdfDocument(fitz.open(url))    # type: ignore
        except Exception:
            message_to_emacs("Failed to load PDF file: " + url)
            return

        # recompute width, height, total number since the file might be modified
        self.document.watch_page_size_change(self.update_page_size)
        self.page_width = self.document.get_page_width()
        self.page_height = self.document.get_page_height()
        self.page_total_number = self.document.page_count

        # Register file watcher, when document is change, re-calling this function.
        self.document.watch_file(url, self.load_document)

        self.update()

    def is_buffer_focused(self):
        # This check is slow, use only when necessary
        try:
            return get_emacs_func_result("eaf-get-path-or-url", []) == self.url
        except Exception:
            return False

    @interactive
    def enter_presentation_mode(self):
        self.presentation_mode = True

        self.scale_before_presentation = self.scale
        self.read_mode_before_presentation = self.read_mode
        self.scroll_offset_before_presentation = self.scroll_offset
        self.start_page_index_before_presentation = self.start_page_index

        self.buffer.enter_fullscreen_request.emit()

        # Make current page fill the view.
        self.zoom_reset("fit_to_presentation")

    @interactive
    def quit_presentation_mode(self):
        self.presentation_mode = False

        self.buffer.exit_fullscreen_request.emit()

        self.scale = self.scale_before_presentation
        if self.start_page_index == self.start_page_index_before_presentation:
            self.scroll_offset = self.scroll_offset_before_presentation
        else:
            self.scroll_offset = self.start_page_index * self.page_height * self.scale

        if self.read_mode_before_presentation == "fit_to_width":
            self.zoom_reset()
        else:
            self.read_mode = "fit_to_customize"
            text_width = self.document.get_page_width()
            fit_to_width = self.rect().width() / text_width
            self.scale_to(min(max(10, fit_to_width), self.scale))
            self.update()

    @interactive
    def toggle_presentation_mode(self):
        '''
        Toggle presentation mode.
        '''
        self.presentation_mode = not self.presentation_mode
        if self.presentation_mode:
            self.enter_presentation_mode()
        else:
            self.quit_presentation_mode()

    @property
    def scroll_step_vertical(self):
        if self.presentation_mode:
            return self.rect().height()
        else:
            return self.rect().size().height() * self.scroll_ratio

    @property
    def scroll_step_horizontal(self):
        if self.presentation_mode:
            return self.rect().width()
        else:
            return self.rect().size().width() * self.scroll_ratio

    @interactive
    def save_current_pos(self):
        self.remember_offset = self.scroll_offset
        self.saved_pos_index = len(self.saved_pos_sequence)
        self.saved_pos_sequence.append(self.scroll_offset)
        message_to_emacs("Saved current position.")

    @interactive
    def jump_to_saved_pos(self):
        if self.remember_offset is None:
            message_to_emacs("Cannot jump from this position.")
        else:
            current_scroll_offset = self.scroll_offset
            self.scroll_offset = self.remember_offset
            self.update()
            self.remember_offset = current_scroll_offset
            message_to_emacs("Jumped to saved position.")

    @interactive
    def jump_to_previous_saved_pos(self):
        if self.saved_pos_index < 0:
            message_to_emacs("No more previous saved postition.")
        else:
            if self.saved_pos_index + 1 == len(self.saved_pos_sequence):
                self.saved_pos_sequence.append(self.scroll_offset)
            self.scroll_offset = self.saved_pos_sequence[self.saved_pos_index]
            self.saved_pos_index = self.saved_pos_index - 1
            self.update()
            message_to_emacs("Jumped to previous saved position.")

    @interactive
    def jump_to_next_saved_pos(self):
        if self.saved_pos_index + 1 >= len(self.saved_pos_sequence):
            message_to_emacs("No more next saved position.")
        else:
            self.scroll_offset = self.saved_pos_sequence[self.saved_pos_index]
            self.saved_pos_index = self.saved_pos_index + 1
            self.update()
            message_to_emacs("Jumped to next saved position.")

    def get_page_pixmap(self, index, scale, rotation=0):
        # Just return cache pixmap when found match index and scale in cache dict.
        if self.page_cache_scale == scale:
            if index in self.page_cache_pixmap_dict.keys():
                return self.page_cache_pixmap_dict[index]
        # Clear dict if page scale changed.
        else:
            self.page_cache_pixmap_dict.clear()
            self.page_cache_scale = scale

        page = self.document[index]
        if self.document.is_pdf:
            page.set_rotation(rotation)

        if self.is_mark_link:
            page.add_mark_link()
        else:
            page.cleanup_mark_link()

        # follow page search text
        if self.is_mark_search:
            page.mark_search_text(self.search_term, self.current_search_quads)
        else:
            page.cleanup_search_text()

        #
        if self.is_mark_select_text:
            page.mark_select_text(self.current_select_text_quads, self.select_text_quads_list)
        else:
            page.cleanup_select_text()

        if self.is_jump_link:
            self.jump_link_key_cache_dict.update(page.mark_jump_link_tips(self.marker_letters))
        else:
            page.cleanup_jump_link_tips()
            self.jump_link_key_cache_dict.clear()

        qpixmap = page.get_qpixmap(scale, self.get_inverted_mode(), self.inverted_image_mode)

        self.page_cache_pixmap_dict[index] = qpixmap
        self.document.cache_page(index, page)

        return qpixmap

    def get_page_render_info(self, index):
        # Get HiDPI scale factor.
        # Note:
        # Don't delete hidpi_scale_factor even it value is 1.0,
        # PDF page will become blurred if delete this variable.
        hidpi_scale_factor = self.devicePixelRatioF()

        # Get page pixmap.
        qpixmap = self.get_page_pixmap(index, self.scale * hidpi_scale_factor, self.rotation)

        page_render_width = qpixmap.width() / hidpi_scale_factor
        page_render_height = qpixmap.height() / hidpi_scale_factor

        return (qpixmap, page_render_width, page_render_height)

    def clean_unused_page_cache_pixmap(self):
        # We need expand render index bound that avoid clean cache around current index.
        index_list = list(range(self.start_page_index, self.last_page_index))

        # Try to clean unused cache.
        cache_index_list = list(self.page_cache_pixmap_dict.keys())

        for cache_index in cache_index_list:
            if cache_index not in index_list:
                self.page_cache_pixmap_dict.pop(cache_index)
                self.document.remove_cache(cache_index)

    def resizeEvent(self, event):
        # Update scale attributes after widget resize.
        self.update_scale()

        QWidget.resizeEvent(self, event)

    def get_inverted_mode(self):
        if self.pdf_dark_mode == "follow":
            if self.theme_mode == "dark":
                # Invert render BLACK font when load dark theme.
                return not self.inverted_mode
            else:
                # Invert render WHITE font when load light theme.
                return self.inverted_mode
        elif self.pdf_dark_mode == "force":
            # Always render WHITE font.
            return True
        else:
            # Always render BLACK font.
            return False

    def get_render_background_color(self):
        if self.pdf_dark_mode == "follow":
            if self.theme_mode == "dark":
                # When load dark theme.
                # Invert render WHITE background, normal render background same as Emacs background.
                return "#FFFFFF" if self.inverted_mode else self.theme_background_color
            else:
                # When load light theme.
                # Invert render BLACK background, normal render background same as Emacs background.
                return "#000000" if self.inverted_mode else self.theme_background_color
        elif self.pdf_dark_mode == "force":
            # When load dark theme, render background same as Emacs background.
            # When load light theme, render BLACK background.
            return self.theme_background_color if self.theme_mode == "dark" else "#000000"
        else:
            # Always render WHITE background.
            return "#FFFFFF"

    def get_render_foreground_color(self):
        if self.pdf_dark_mode == "follow":
            # Render invert color.
            return self.theme_background_color if self.inverted_mode else self.theme_foreground_color
        elif self.pdf_dark_mode == "force":
            # Always render light color.
            return self.theme_foreground_color if self.theme_mode == "dark" else self.theme_background_color
        else:
            # Alwasy render BLACK font.
            return "#000000"

    def paintEvent(self, event):
        # update page base information
        self.update_page_index()

        # Init painter.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        painter.save()

        # Draw background.
        color = QColor(self.get_render_background_color())
        painter.setBrush(color)
        painter.setPen(color)

        # Draw page.
        if self.read_mode == "fit_to_presentation":
            self.draw_presentation_page(painter, self.start_page_index)
        else:
            self.draw_scroll_pages(painter)

        # Clean unused pixmap cache that avoid use too much memory.
        self.clean_unused_page_cache_pixmap()

        # Restore painter.
        painter.restore()

        # Render progress information.  # type: ignore
        painter.setPen(QColor(self.get_render_foreground_color()))
        self.update_page_progress(painter)

        if self.is_mark_search and not self.document.is_pdf and self.current_search_quads and self.current_search_page:
            x0, y0, x1, y1 = self.current_search_quads.rect
            page_offset = self.scroll_offset - (self.current_search_page) * self.scale * self.page_height

            x, y = (x0 - 10 + self.page_render_x/2) * self.scale, y1 * self.scale-page_offset
            # print(self.current_search_quads.rect)
            # pos = QPoint(x, y)
            self.draw_arrow_indicator(painter, int(x), int(y)-3)

    def draw_presentation_page(self, painter, index):
        # Get page render information.
        (qpixmap, self.page_render_width, self.page_render_height) = self.get_page_render_info(index)

        # Select char area when is_select_mode is True.
        if self.is_select_mode:
            qpixmap = self.mark_select_char_area(index, qpixmap)

        # Init x and y coordinate.
        self.page_render_x = (self.rect().width() - self.page_render_width) / 2
        self.page_render_y = (self.rect().height() - self.page_render_height) / 2

        # Adjust coordinate and size when actual size smaller than visiable area.
        page_proportion = self.page_render_height * 1.0 / self.page_render_width

        if page_proportion > 1:
            self.page_render_y = 0

            if self.rect().height() > self.page_render_height:
                self.page_render_height = self.rect().height()
                self.page_render_width = self.page_render_height / page_proportion
        else:
            self.page_render_x = 0

            if self.rect().width() > self.page_render_width:
                self.page_render_width = self.rect().width()
                self.page_render_height = self.page_render_width * page_proportion

        # Draw page.
        rect = QRect(int(self.page_render_x), int(self.page_render_y), int(self.page_render_width), int(self.page_render_height))
        painter.drawRect(rect)
        painter.drawPixmap(rect, qpixmap)

    def draw_scroll_pages(self, painter):
        # Record start page index before change page.
        old_start_page_index = self.start_page_index

        # Calcucate render range.
        self.start_page_index = min(
            int(self.scroll_offset * 1.0 / self.scale / self.page_height),
            self.page_total_number - 1)

        self.last_page_index = min(
            int((self.scroll_offset + self.rect().height()) * 1.0 / self.scale / self.page_height + 2),
            self.page_total_number)

        # We need adjust scroll offset if the actual height of the page is lower than the theoretical height returned by mupdf.
        (_, _, page_render_height) = self.get_page_render_info(self.start_page_index)
        if self.page_height * self.scale - page_render_height > 0:
            self.scroll_offset += (self.start_page_index - old_start_page_index) * self.scroll_step_vertical

            # Avoid scroll offset out of round.
            self.scroll_offset = max(0, min(self.scroll_offset, self.max_scroll_offset()))

        # Translate coordinate with scroll offset.
        painter.translate(0,  -self.scroll_offset)

        for index in list(range(self.start_page_index, self.last_page_index)):
            # Draw page.
            self.draw_scroll_page(painter, index)

            # Draw an indicator for synctex position
            if self.synctex_info.page_num == index + 1 and self.synctex_info.pos_y is not None:
                pos_y = int(self.page_render_y + self.synctex_info.pos_y * self.scale)
                self.draw_arrow_indicator(painter, 15, pos_y)
            elif self.link_page_num == index + 1 and self.link_page_offset_y is not None:
                pos_x = int(self.page_render_x + self.link_page_offset_x)
                pos_y = int(self.page_render_y + self.link_page_offset_y)
                pos_x = max(0, pos_x - 30)
                pos_y = pos_y + 12
                self.draw_arrow_indicator(painter, pos_x, pos_y)

    def draw_scroll_page(self, painter, index):
        # Draw page padding.
        if index != 0:
            painter.translate(0, self.page_padding)

        # Get page render information.
        (qpixmap, self.page_render_width, self.page_render_height) = self.get_page_render_info(index)

        # Select char area when is_select_mode is True.
        if self.is_select_mode:
            qpixmap = self.mark_select_char_area(index, qpixmap)

        # Init x coordinate.
        self.page_render_x = (self.rect().width() - self.page_render_width) / 2

        # Adjust x coordinate coordinate of render page.
        if self.read_mode == "fit_to_customize" and self.page_render_width >= self.rect().width():
            # limit the visiable area size
            self.page_render_x = max(min(self.page_render_x + self.horizontal_offset, 0), self.rect().width() - self.page_render_width)

        # Render page with page index, scale and page height.
        self.page_render_y = index * self.scale * self.page_height

        # NOTE:
        # We need translate coordinate inverse if the actual height of the page is lower than the theoretical height returned by mupdf.
        # otherwise, padding between two pages will become too big.
        height_deviation = (self.page_height * self.scale - self.page_render_height)

        if self.scroll_offset < self.max_scroll_offset() - self.page_height:
            # Scroll up deviation between actual height and render height.
            painter.translate(0, -height_deviation)
        else:
            # Scroll down to avoid padding after last page.
            painter.translate(0, height_deviation)

        # Draw page.
        rect = QRect(int(self.page_render_x), int(self.page_render_y), int(self.page_render_width), int(self.page_render_height))
        painter.drawRect(rect)
        painter.drawPixmap(rect, qpixmap)

    def draw_arrow_indicator(self, painter, x, y):
        from PyQt6.QtGui import QPolygon

        painter.save()
        arrow = QPolygon([QPoint(x, y), QPoint(x+13, y), QPoint(x+13, y-4),
                          QPoint(x+21, y+3),
                          QPoint(x+13, y+10), QPoint(x+13, y+6), QPoint(x, y+6),
                          QPoint(x, y)])
        fill_color = QColor(236, 96, 31, 255)
        border_color = QColor(255, 91, 15, 255)
        painter.setBrush(fill_color)
        painter.setPen(border_color)
        painter.drawPolygon(arrow)
        QTimer().singleShot(5000, self.clear_arrow_indicator)
        painter.restore()

    def clear_arrow_indicator(self):
        self.synctex_info.reset()
        self.link_page_num = None
        self.link_page_offset_y = None

    def update_page_progress(self, painter):
        # Show in mode-line-position
        eval_in_emacs("eaf--pdf-update-position", [self.buffer_id,
                                                   self.current_page_index,
                                                   self.page_total_number])

        # Draw progress on page.
        show_progress_on_page, = get_emacs_vars(["eaf-pdf-show-progress-on-page"])
        if show_progress_on_page:
            bottom = int(self.rect().height() - self.page_annotate_padding_y)
            right = int(min((self.rect().width() + self.page_render_width)/2, self.rect().width()) - self.page_annotate_padding_x)
            x, y = w, h = right//2, bottom//2
            progress_rect = QRect(x, y, w, h)

            base_progress_font_size = self.default_progress_font_size
            if type(show_progress_on_page) == int:
                base_progress_font_size = show_progress_on_page


            progress_font_size = int((1-0.6*math.exp(-1.5*(self.scale-1))) * base_progress_font_size)
            progress_font = QFont()
            progress_font.setPixelSize(progress_font_size)
            painter.setFont(progress_font)
            painter.drawText(progress_rect,
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                             self.get_page_progress())

    def get_page_progress(self):
        progress_percent = int(self.current_page_index * 100 / self.page_total_number)

        return "{}% [{}/{}]".format(progress_percent,
                                      self.current_page_index,
                                      self.page_total_number)

    def build_context_wrap(f):    # type: ignore
        def wrapper(*args):
            # Get self instance object.
            self_obj = args[0]

            # Record page before action.
            page_before_action = self_obj.start_page_index

            # Do action.
            ret = f(*args)    # type: ignore

            # Record page after action.
            page_after_action = self_obj.start_page_index
            self_obj.is_page_just_changed = (page_before_action != page_after_action)

            # Start build context timer.
            self_obj.last_action_time = time.time()
            QTimer().singleShot(self_obj.page_cache_context_delay, self_obj.build_context_cache)

            return ret

        return wrapper

    @build_context_wrap    # type: ignore
    def wheelEvent(self, event):
        if not event.accept():
            if event.angleDelta().y():
                numSteps = event.angleDelta().y()
                if self.presentation_mode:
                    # page scrolling
                    curtime = time.time()
                    if curtime - self.scroll_wheel_lasttime > 0.1:
                        numSteps = 1 if numSteps > 0 else -1
                        self.scroll_wheel_lasttime = curtime
                    else:
                        numSteps = 0
                else:
                    # fixed pixel scrolling
                    numSteps = numSteps / 120
                new_pos = self.scroll_offset - numSteps * self.scroll_step_vertical
                max_pos = self.max_scroll_offset()
                self.update_vertical_offset(max(min(new_pos, max_pos), 0))    # type: ignore

            if event.angleDelta().x():
                new_pos = (self.horizontal_offset + event.angleDelta().x() / 120 * self.scroll_step_horizontal)
                max_pos = (self.page_width * self.scale - self.rect().width())
                self.update_horizontal_offset(max(min(new_pos , max_pos), -max_pos))    # type: ignore

    def update_page_index(self):
        # Don't adjust start_page_index if is in presentation mode.
        if self.read_mode != "fit_to_presentation":
            self.start_page_index = min(int(self.scroll_offset * 1.0 / self.scale / self.page_height),
                                        self.page_total_number - 1)

        if self.scroll_offset == 0:
            self.current_page_index = 1
        elif self.scroll_offset == self.max_scroll_offset():
            self.current_page_index = self.page_total_number
        else:
            self.current_page_index = max(math.ceil(((self.scroll_offset + self.rect().height() * 5.0 / 9.0) / self.scale / self.page_height)),
                                          self.start_page_index + 1)
        self.last_page_index = min(int((self.scroll_offset + self.rect().height()) * 1.0 / self.scale / self.page_height) + 1,
                                   self.page_total_number)

    def update_page_size(self, rect):
        current_page_index = self.start_page_index
        self.page_width = rect.width
        self.page_height = rect.height
        self.jump_to_page(current_page_index)    # type: ignore

    def build_context_cache(self):
        # Just build context cache when action duration longer than delay
        # Don't build contexnt cache when is_page_just_changed is True, avoid flickr when user change page.
        last_action_duration = (time.time() - self.last_action_time) * 1000
        if last_action_duration > self.page_cache_context_delay and not self.is_page_just_changed:
            for index in list(range(self.start_page_index, self.last_page_index)):
                self.get_page_pixmap(index, self.scale, self.rotation)

    def scale_to(self, new_scale):
        self.scroll_offset = new_scale * 1.0 / self.scale * self.scroll_offset
        self.scale = new_scale

    def scale_to_width(self):
        self.scale_to(self.rect().width() * 1.0 / self.page_width)

    def scale_to_presentation(self):
        self.scale_to(min(self.rect().width() * 1.0 / self.page_width,
                          self.rect().height() * 1.0 / self.page_height))

    def update_scale(self):
        if self.read_mode == "fit_to_width":
            self.scale_to_width()
        elif self.read_mode == "fit_to_presentation":
            self.scale_to_presentation()

    def max_scroll_offset(self):
        max_scroll_offset = self.scale * self.page_height * self.page_total_number - self.rect().height()
        if max_scroll_offset < 0:
            max_scroll_offset = 0
        return max_scroll_offset

    @interactive
    def reload_document(self):
        message_to_emacs("Reloaded PDF file!")
        self.load_document(self.url)

    @interactive
    def toggle_read_mode(self):
        if self.read_mode == "fit_to_customize":
            self.read_mode = "fit_to_width"
        elif self.read_mode == "fit_to_width":
            self.read_mode = "fit_to_presentation"
        elif self.read_mode == "fit_to_presentation":
            self.read_mode = "fit_to_width"

        self.update_scale()
        self.update()

    def next_page(self):
        if self.start_page_index < self.page_total_number - 1:
            self.start_page_index = self.start_page_index + 1
            self.update()

    def prev_page(self):
        if self.start_page_index > 0:
            self.start_page_index = self.start_page_index - 1
            self.update()

    @interactive
    def scroll_up(self):
        if self.read_mode == "fit_to_presentation":
            self.next_page()
        else:
            self.update_vertical_offset(min(self.scroll_offset + self.scroll_step_vertical, self.max_scroll_offset()))    # type: ignore

    @interactive
    def scroll_down(self):
        if self.read_mode == "fit_to_presentation":
            self.prev_page()
        else:
            self.update_vertical_offset(max(self.scroll_offset - self.scroll_step_vertical, 0))    # type: ignore

    @interactive
    def scroll_up_page(self):
        if self.presentation_mode:
            self.next_page()
        else:
            # Adjust scroll step to make users continue reading fluently.
            self.update_vertical_offset(min(self.scroll_offset + self.rect().height() - self.scroll_step_vertical, self.max_scroll_offset()))    # type: ignore

    @interactive
    def scroll_down_page(self):
        if self.presentation_mode:
            self.prev_page()
        else:
            # Adjust scroll step to make users continue reading fluently.
            self.update_vertical_offset(max(self.scroll_offset - self.rect().height() + self.scroll_step_vertical, 0))    # type: ignore

    @interactive
    def scroll_right(self):
        self.update_horizontal_offset(max(self.horizontal_offset - self.scroll_step_horizontal, (self.rect().width() - self.page_width * self.scale) / 2))    # type: ignore

    @interactive
    def scroll_left(self):
        self.update_horizontal_offset(min(self.horizontal_offset + self.scroll_step_horizontal, (self.page_width * self.scale - self.rect().width()) / 2))    # type: ignore

    @interactive
    def scroll_center_horizontal(self):
        self.update_horizontal_offset(0)    # type: ignore

    @interactive
    def scroll_to_begin(self):
        self.buffer.mark_position()
        self.update_vertical_offset(0)    # type: ignore

    @interactive
    def scroll_to_end(self):
        self.buffer.mark_position()
        self.update_vertical_offset(self.max_scroll_offset())    # type: ignore

    @interactive
    def zoom_in(self):
        self.read_mode = "fit_to_customize"
        text_width = self.document.get_page_width()
        fit_to_width = self.rect().width() / text_width
        self.scale_to(min(max(10, fit_to_width), self.scale + self.pdf_zoom_step))
        self.update()

    @interactive
    def zoom_out(self):
        self.read_mode = "fit_to_customize"
        self.scale_to(max(1, self.scale - self.pdf_zoom_step))
        self.update()

    @interactive
    def zoom_fit_text_width(self):
        self.read_mode = "fit_to_customize"
        text_width = self.document.get_page_width()
        self.scale_to(self.rect().width() / text_width)
        self.scroll_center_horizontal()
        self.update()

    @interactive
    def zoom_close_to_text_width(self):
        self.read_mode = "fit_to_customize"
        text_width = self.document.get_page_width()
        self.scale_to(self.rect().width() * 0.9 / text_width)
        self.scroll_center_horizontal()
        self.update()

    @interactive
    def zoom_reset(self, read_mode="fit_to_width"):
        if self.is_mark_search:
            self.cleanup_search()
        self.read_mode = read_mode
        self.update_scale()
        self.update()

    @interactive
    def toggle_trim_white_margin(self):
        current_page_index = self.start_page_index
        self.document.toggle_trim_margin()
        self.page_cache_pixmap_dict.clear()
        self.update()
        self.jump_to_page(current_page_index)    # type: ignore

    @interactive
    def toggle_inverted_mode(self):
        # Need clear page cache first, otherwise current page will not inverted until next page.
        self.page_cache_pixmap_dict.clear()

        self.inverted_mode = not self.inverted_mode
        self.update()
        return

    @interactive
    def toggle_inverted_image_mode(self):
        # Toggle inverted image status.
        if not self.document.is_pdf:
            message_to_emacs("Only support PDF!")
            return

        self.page_cache_pixmap_dict.clear()
        self.inverted_image_mode = not self.inverted_image_mode

        # Re-render page.
        self.update()

    @interactive
    def toggle_mark_link(self): #  mark_link will add underline mark on link, using prompt link position.
        self.is_mark_link = not self.is_mark_link and self.document.is_pdf
        self.page_cache_pixmap_dict.clear()
        self.update()

    def update_rotate(self, rotate):
        if self.document.is_pdf:
            current_page_index = self.start_page_index
            self.rotation = rotate
            self.page_width, self.page_height = self.page_height, self.page_width

            # Need clear page cache first, otherwise current page will not inverted until next page.
            self.page_cache_pixmap_dict.clear()
            self.update_scale()
            self.update()
            self.jump_to_page(current_page_index)    # type: ignore
        else:
            message_to_emacs("Only support PDF!")

    @interactive
    def rotate_clockwise(self):
        self.update_rotate((self.rotation + 90) % 360)

    def add_annot_of_action(self, annot_action):
        new_annot = None
        page = self.document[annot_action.page_index]
        quads = annot_action.annot_quads
        if (annot_action.annot_type == fitz.PDF_ANNOT_HIGHLIGHT):
            new_annot = page.add_highlight_annot(quads)
            new_annot.set_colors(stroke=annot_action.annot_stroke_color)
            new_annot.update()
        elif (annot_action.annot_type == fitz.PDF_ANNOT_STRIKE_OUT):
            new_annot = page.add_strikeout_annot(quads)
        elif (annot_action.annot_type == fitz.PDF_ANNOT_UNDERLINE):
            new_annot = page.add_underline_annot(quads)
            new_annot.set_colors(stroke=annot_action.annot_stroke_color)
            new_annot.update()
        elif (annot_action.annot_type == fitz.PDF_ANNOT_SQUIGGLY):
            new_annot = page.add_squiggly_annot(quads)
        elif (annot_action.annot_type == fitz.PDF_ANNOT_TEXT):
            new_annot = page.add_text_annot(annot_action.annot_top_left_point,
                                          annot_action.annot_content, icon="Note")
        elif (annot_action.annot_type == fitz.PDF_ANNOT_FREE_TEXT):
            color = QColor(self.inline_text_annot_color)
            color_r, color_g, color_b = color.redF(), color.greenF(), color.blueF()
            text_color = [color_r, color_g, color_b]
            new_annot = page.add_freetext_annot(annot_action.annot_rect,
                                              annot_action.annot_content,
                                              fontsize=self.inline_text_annot_fontsize,
                                              fontname="Arial",
                                              text_color=text_color, align=0)
        elif (annot_action.annot_type == fitz.PDF_ANNOT_SQUARE):
            new_annot = page.add_rect_annot(annot_action.annot_rect)

        if new_annot:
            new_annot.set_info(title=annot_action.annot_title)
            new_annot.parent = page
            self.save_annot()

    def delete_annot_of_action(self, annot_action):
        page = self.document[annot_action.page_index]
        annot = AnnotAction.find_annot_of_annot_action(page, annot_action)
        if annot:
            page.delete_annot(annot)
            self.save_annot()

    @interactive
    def rotate_counterclockwise(self):
        self.update_rotate((self.rotation - 90) % 360)

    @interactive
    def undo_annot_action(self):
        if (self.annot_action_index < 0):
            message_to_emacs("No further undo action!")
        else:
            annot_action = self.annot_action_sequence[self.annot_action_index]
            self.annot_action_index = self.annot_action_index - 1
            if annot_action:
                self.jump_to_page(annot_action.page_index)    # type: ignore
                if annot_action.action_type == "Add":
                    self.delete_annot_of_action(annot_action)
                elif annot_action.action_type == "Delete":
                    self.add_annot_of_action(annot_action)
                message_to_emacs("Undo last action!")
            else:
                message_to_emacs("Invalid annot action.")

    @interactive
    def redo_annot_action(self):
        if (self.annot_action_index + 1 >= len(self.annot_action_sequence)):
            message_to_emacs("No further redo action!")
        else:
            self.annot_action_index = self.annot_action_index + 1
            annot_action = self.annot_action_sequence[self.annot_action_index]
            self.jump_to_page(annot_action.page_index)    # type: ignore

            if annot_action.action_type == "Add":
                self.add_annot_of_action(annot_action)
            elif annot_action.action_type == "Delete":
                self.delete_annot_of_action(annot_action)

            message_to_emacs("Redo last action!")


    def add_mark_jump_link_tips(self):
        self.is_jump_link = True and self.document.is_pdf
        self.page_cache_pixmap_dict.clear()
        self.update()

    def jump_to_link(self, key):
        key = key.upper()
        if key in self.jump_link_key_cache_dict:
            self.handle_jump_to_link(self.jump_link_key_cache_dict[key])
        self.cleanup_links()

    def handle_jump_to_link(self, link, external_browser=False):
        if "page" in link:
            self.cleanup_links()
            self.save_current_pos()
            self.buffer.mark_position()

            target_point = link["to"]
            offset_y_from_top = self.page_height - target_point.y if self.document.is_pdf else target_point.y
            link_offset = (link["page"] * self.page_height + offset_y_from_top) * self.scale
            self.link_page_num = link["page"] + 1
            self.link_page_offset_x = target_point.x * self.scale
            self.link_page_offset_y = offset_y_from_top * self.scale
            self.jump_to_offset(link_offset)
            message_to_emacs("Landed on Page " + str(self.link_page_num))
        elif "uri" in link:
            self.cleanup_links()

            if external_browser:
                webbrowser.open(link["uri"])
                message_to_emacs("Open in external browser: " + link["uri"])
            else:
                from core.utils import open_url_in_new_tab
                open_url_in_new_tab(link["uri"])
                message_to_emacs("Open in EAF: " + link["uri"])

    def cleanup_links(self):
        self.is_jump_link = False
        self.page_cache_pixmap_dict.clear()
        self.update()

    def _merge_quads_list(self, quads_list):
        min_x = float('inf')
        min_y = float('inf')
        max_x = float('-inf')
        max_y = float('-inf')
        for quad in quads_list:
            points = [quad.ul, quad.ur, quad.lr, quad.ll]
            for point in points:
                if point.x < min_x:
                    min_x = point.x
                if point.y < min_y:
                    min_y = point.y
                if point.x > max_x:
                    max_x = point.x
                if point.y > max_y:
                    max_y = point.y
        ul = fitz.Point(min_x, min_y)
        ur = fitz.Point(max_x, min_y)
        lr = fitz.Point(max_x, max_y)
        ll = fitz.Point(min_x, max_y)
        return fitz.Quad(ul, ur, ll, lr)

    def _word_to_quads(self, word):
        x0, y0, x1, y1 = word[0],word[1], word[2],word[3]

        ul = fitz.Point(x0, y0)  # ul
        ur = fitz.Point(x1, y0)  # ur
        ll = fitz.Point(x0, y1)  # ll
        lr = fitz.Point(x1, y1)  # lr

        return fitz.Quad(ul, ur, ll, lr)

    def _find_word_index(self, words_list, word):
        for i in range(len(words_list)):
            for j in range(len(words_list[i])):
                if words_list[i][j] == word:
                    return (i, j)
        return None


    def _keyboard_select_text(self, word, expand=False):
        index = self._find_word_index(self.select_text_words_list, word)

        if index:
            i, j = index
            self.select_text_words_list[i] = self.select_text_words_list[i][:j]
            if j > 0:
                i += 1
            while i < len(self.select_text_words_list):
                self.select_text_words_list.pop()
        else:
            if len(self.select_text_words_list) == 0:
                self.select_text_words_list.append([word])
            else:
                last_word = self.select_text_words_list[-1][-1]
                block_begin, line_begin, word_begin = last_word[5],last_word[6],last_word[7]
                block_end, line_end, word_end = word[5],word[6],word[7]
                word_begin += 1
                while line_begin < line_end:
                    self.select_text_words_list[-1].extend(self.current_page_words[block_begin][line_begin][word_begin:])
                    line_begin += 1
                    word_begin = 0
                    self.select_text_words_list.append([])
                self.select_text_words_list[-1].extend(self.current_page_words[block_end][line_end][word_begin:word_end+1])
        self.current_select_text_quads = self._word_to_quads(word)
        print(self.current_select_text_quads)
        self.select_text_quads_list = [self._merge_quads_list([self._word_to_quads(word) for word in words]) for words in self.select_text_words_list ]
        offset = ((self.current_page_index - 1) * self.page_height + self.current_select_text_quads.ul.y) * self.scale
        self.jump_to_offset(offset)

    def _search_in_pages(self, text, page_list):
        for page_index in page_list:
            # Search from the current page
            page = self.document[page_index]
            if page_index < self.current_page_index:
                self.search_text_index = len(self.search_text_quads_list)

            if support_hit_max:
                quads_list = self.document.search_page_for(page_index, text, hit_max=999, quads=True)
            else:
                quads_list = self.document.search_page_for(page_index, text, quads=True)
            if quads_list:
                for index, quad in enumerate(quads_list):
                    search_text_offset = (page_index * self.page_height + quad.ul.y) * self.scale
                    self.search_text_offset_list.append(search_text_offset)
                    self.search_text_quads_list.append(quad)
                self.search_page_history.add(page)
        return quads_list

    def keyboard_select_text(self, word, expand=False):
        self.is_mark_select_text = True
        self.page_cache_pixmap_dict.clear()
        if not expand:
            self.select_text_words_list.clear()
            self.select_text_quads_list.clear()
        self._keyboard_select_text(word, expand=False)
        self.update()



    def search_text(self, text, page_num = None, page_offset=-1):
        self.is_mark_search = True
        if page_num is not None: # clear soft hyphen in the line
            text = text.strip(" -‐")
        self.current_search_page = page_num
        self.search_term = text
        self.last_search_term = text
        self.page_cache_pixmap_dict.clear()
        self.search_text_offset_list.clear()
        self.search_text_quads_list.clear()

        if self.search_term == "":
            for page in self.search_page_history:
                page.cleanup_search_text()
            self.page_cache_pixmap_dict.clear()
            self.search_page_history.clear()
            self.update()
            return

        self.search_text_index = 0

        page_list = [page_num] if page_num is not None else range(self.page_total_number)
        self._search_in_pages(self.search_term, page_list)

        if(len(self.search_text_offset_list) == 0):
            message_to_emacs("No results found with \"" + self.search_term + "\".")
            if page_num is not None:
                self.jump_to_page(page_num+1)
            self.is_mark_search = False
        else:
            try:
                idx = page_offset if page_offset != -1 else self.search_text_index
                self.jump_to_offset(self.search_text_offset_list[idx])
                self.current_search_quads = self.search_text_quads_list[idx]
                self.page_cache_pixmap_dict.clear()
                self.update()
                vertical_offset = self.search_text_offset_list[idx]
                if page_num is not None: # if search line ,move highlight to center
                    vertical_offset -= self.page_height // 4
                self.update_vertical_offset(vertical_offset)    # type: ignore
            except Exception as e: # more debug info
                print(e, idx, self.search_text_offset_list)
                print(page_offset, self.search_text_index)
                message_to_emacs("Unexpected error while searching: " + self.search_term)
                self.is_mark_search = False


    def jump_next_match(self):
        if len(self.search_text_offset_list) > 0:
            self.search_text_index = (self.search_text_index + 1) % len(self.search_text_offset_list)
            self.jump_to_offset(self.search_text_offset_list[self.search_text_index])
            message_to_emacs(str(self.search_text_index + 1) + "/" + str(len(self.search_text_offset_list)), False, False)
            self.current_search_quads = self.search_text_quads_list[self.search_text_index]
            self.page_cache_pixmap_dict.clear()
            self.update()

    def jump_last_match(self):
        if len(self.search_text_offset_list) > 0:
            self.search_text_index = (self.search_text_index - 1) % len(self.search_text_offset_list)
            self.jump_to_offset(self.search_text_offset_list[self.search_text_index])
            message_to_emacs(str(self.search_text_index + 1) + "/" + str(len(self.search_text_offset_list)), False, False)
            self.current_search_quads = self.search_text_quads_list[self.search_text_index]
            self.page_cache_pixmap_dict.clear()
            self.update()

    def cleanup_search(self):
        self.is_mark_search = False
        self.search_mode_forward = False
        self.search_mode_backward = False
        self.current_search_quads = None
        self.search_term = ""
        self.page_cache_pixmap_dict.clear()
        self.search_text_offset_list.clear()
        self.search_text_quads_list.clear()
        self.update()

    def get_select_char_list(self):
        page_dict = {}
        if self.start_char_rect_index and self.last_char_rect_index:
            # start and last page
            sp_index = min(self.start_char_page_index, self.last_char_page_index)    # type: ignore
            lp_index = max(self.start_char_page_index, self.last_char_page_index)    # type: ignore
            for page_index in range(sp_index, lp_index + 1):    # type: ignore
                page_char_list = self.document[page_index].get_page_char_rect_list()

                if page_char_list:
                # handle forward select and backward select on multi page.
                # backward select on multi page.
                    if self.start_char_page_index > self.last_char_page_index:    # type: ignore
                        sc = self.last_char_rect_index if page_index == sp_index else 0
                        lc = self.start_char_rect_index if page_index == lp_index else len(page_char_list)
                    else:
                        # forward select on multi page.
                        sc = self.start_char_rect_index if page_index == sp_index else 0
                        lc = self.last_char_rect_index if page_index == lp_index else len(page_char_list)

                    # handle forward select and backward select on same page.
                    sc_index = min(sc, lc)
                    lc_index = max(sc, lc)

                    page_dict[page_index] = page_char_list[sc_index : lc_index + 1]

        return page_dict

    def parse_select_char_list(self):
        string = ""
        page_dict = self.get_select_char_list()
        for index, chars_list in enumerate(page_dict.values()):
            if chars_list:
                string += "".join(list(map(lambda x: x["c"], chars_list)))

                if index != 0:
                    string += "\n\n"    # add new line on page end.
        return string

    def record_new_annot_action(self, annot_action):
        num_action_removed = len(self.annot_action_sequence) - (self.annot_action_index + 1)
        if num_action_removed > 0:
            del self.annot_action_sequence[-num_action_removed:]
        self.annot_action_sequence.append(annot_action)
        self.annot_action_index += 1

    def annot_select_char_area(self, annot_type="highlight", text=None):
        self.cleanup_select()   # needs first cleanup select highlight mark.
        for page_index, quads in self.select_area_annot_quad_cache_dict.items():
            page = self.document[page_index]

            if annot_type == "highlight":
                new_annot = page.add_highlight_annot(quads)
                qcolor = QColor(self.text_highlight_annot_color)
                new_annot.set_colors(stroke=qcolor.getRgbF()[0:3])
                new_annot.update()
            elif annot_type == "strikeout":
                new_annot = page.add_strikeout_annot(quads)
            elif annot_type == "underline":
                new_annot = page.add_underline_annot(quads)
                qcolor = QColor(self.text_underline_annot_color)
                new_annot.set_colors(stroke=qcolor.getRgbF()[0:3])
                new_annot.update()
            elif annot_type == "squiggly":
                new_annot = page.add_squiggly_annot(quads)
            else:                    # annot_type == "text"
                point = quads[-1].lr # lower right point
                new_annot = page.add_text_annot(point, text, icon="Note")

            new_annot.set_info(title=self.user_name)
            new_annot.parent = page

            annot_action = AnnotAction.create_annot_action("Add", page_index, new_annot)
            self.record_new_annot_action(annot_action)

        self.document.saveIncr()
        self.select_area_annot_quad_cache_dict.clear()

    def annot_popup_text_annot(self, text=None):
        (point, page_index) = self.popup_text_annot_pos
        if point is None or page_index is None:
            return

        page = self.document[page_index]
        new_annot = page.add_text_annot(point, text, icon="Note")
        new_annot.set_info(title=self.user_name)
        new_annot.parent = page

        annot_action = AnnotAction.create_annot_action("Add", page_index, new_annot)
        self.record_new_annot_action(annot_action)

        self.save_annot()
        self.disable_popup_text_annot_mode()    # type: ignore

    def compute_annot_rect_inline_text(self, point, fontsize, text):
        text_lines = text.splitlines()
        longest_line = max(text_lines, key=len)
        len_eng = len(longest_line)
        len_utf8 = len(longest_line.encode('utf-8'))
        len_real = int((len_utf8 - len_eng) / 2 + len_eng)
        annot_rect = fitz.Rect(point,
                               point.x + (fontsize / 1.5) * len_real,
                               point.y + (fontsize * 1.3) * len(text_lines))
        return annot_rect


    def annot_inline_text_annot(self, text=None):
        (point, page_index) = self.inline_text_annot_pos
        if point is None or page_index is None:
            return

        page = self.document[page_index]
        fontname = "Arial"
        fontsize = self.inline_text_annot_fontsize
        annot_rect = self.compute_annot_rect_inline_text(point, fontsize, text)
        color = QColor(self.inline_text_annot_color)
        color_r, color_g, color_b = color.redF(), color.greenF(), color.blueF()
        text_color = [color_r, color_g, color_b]
        new_annot = page.add_freetext_annot(annot_rect, text,
                                          fontsize=fontsize, fontname=fontname,
                                          text_color=text_color, align = 0)
        new_annot.set_info(title=self.user_name)
        new_annot.parent = page

        annot_action = AnnotAction.create_annot_action("Add", page_index, new_annot)
        self.record_new_annot_action(annot_action)

        self.save_annot()
        self.disable_inline_text_annot_mode()    # type: ignore

    def cleanup_select(self):
        self.is_select_mode = False
        self.delete_all_mark_select_area()
        self.page_cache_pixmap_dict.clear()
        self.update()

    def update_select_char_area(self):
        page_dict = self.get_select_char_list()
        for page_index, chars_list in page_dict.items():
            # Using multi line rect make of abnormity select area.
            line_rect_list = []
            if chars_list:
                # every char has bbox property store char rect.
                bbox_list = list(map(lambda x: x["bbox"], chars_list))

                # With char order is left to right, if the after char x-axis more than before
                # char x-axis, will determine have "\n" between on both.
                if len(bbox_list) >= 2:
                    tl_x, tl_y = 0, 0 # top left point
                    for index, bbox in enumerate(bbox_list[:-1]):
                        if (tl_x == 0) or (tl_y == 0):
                            tl_x, tl_y = bbox[:2]
                        if bbox[0] > bbox_list[index + 1][2]:
                            br_x, br_y = bbox[2:] # bottom right
                            line_rect_list.append((tl_x, tl_y, br_x, br_y))
                            tl_x, tl_y = 0, 0

                    lc = bbox_list[-1]  # The last char
                    line_rect_list.append((tl_x, tl_y, lc[2], lc[3]))
                else:
                    # if only one char selected.
                    line_rect_list.append(bbox_list[0])

            def check_rect(rect):
                tl_x, tl_y, br_x, br_y = rect
                if tl_x <= br_x and tl_y <= br_y:
                    return fitz.Rect(rect)
                # discard the illegal rect. return a micro rect
                return fitz.Rect(tl_x, tl_y, tl_x+1, tl_y+1)

            line_rect_list = list(map(check_rect, line_rect_list))

            quad_list = list(map(lambda x: x.quad, line_rect_list))

            # refresh select quad
            self.select_area_annot_quad_cache_dict[page_index] = quad_list

    def mark_select_char_area(self, page_index, pixmap):
        def quad_to_qrect(quad):
            qrect = quad.rect * self.scale * self.devicePixelRatioF()
            rect = QRect(int(qrect.x0), int(qrect.y0), int(qrect.width), int(qrect.height))
            return rect

        qp = QPainter(pixmap)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        qp.save()

        # clear old highlight
        if page_index in self.select_area_annot_quad_cache_dict:
            old_quads = self.select_area_annot_quad_cache_dict[page_index]
            foreground_color = "#000000" if self.inverted_mode else "#FFFFFF"
            for quad in old_quads:
                qp.fillRect(quad_to_qrect(quad), QColor(foreground_color))

        # update select area quad list
        self.update_select_char_area()

        # draw new highlight
        if page_index in self.select_area_annot_quad_cache_dict:
            quads = self.select_area_annot_quad_cache_dict[page_index]
            for quad in quads:
                qp.fillRect(quad_to_qrect(quad), QColor(self.text_highlight_annot_color))

        qp.restore()
        return pixmap

    def delete_all_mark_select_area(self):
        self.last_char_page_index = None
        self.last_char_rect_index = None
        self.start_char_page_index = None
        self.start_char_rect_index = None

    def get_annots(self, page_index, types=None):
        '''
        Return a list of annotations on page_index of types.
        '''
        # Notes: annots need the pymupdf above 1.16.4 version.
        page = self.document[page_index]
        return page.annots(types)

    def find_annot_by_id(self, page, annot_id):
        annot = page.first_annot
        if not annot:
            return None

        while annot:
            if annot.info["id"] == annot_id:
                return annot
            annot = annot.next

        return None

    def check_annot(self):
        ex, ey, page_index = self.get_cursor_absolute_position()    # type: ignore
        if page_index is None or page_index >= self.document.page_count:
            return

        page = self.document[page_index]

        annot, ok = page.can_update_annot(ex, ey)
        if not ok:
            return

        self.is_hover_annot = annot is not None

        self.hovered_annot = annot
        self.page_cache_pixmap_dict.pop(page_index, None)
        self.update()

    def save_annot(self):
        self.document.saveIncr()
        self.page_cache_pixmap_dict.clear()
        self.update()

    def annot_handler(self, action=None, annot=None):
        annot = annot or self.hovered_annot
        if annot is None:
            return
        if annot.parent:
            if action == "delete":
                annot_action = AnnotAction.create_annot_action("Delete", annot.parent.number, annot)
                self.record_new_annot_action(annot_action)
                annot.parent.delete_annot(annot)
                self.save_annot()
            elif action == "edit":
                self.edited_annot_page = (annot, annot.parent)
                atomic_edit(self.buffer_id, annot.info["content"].replace("\r", "\n"))
            elif action == "move":
                self.moved_annot_page = (annot, annot.parent)
                if annot.type[0] == fitz.PDF_ANNOT_TEXT or \
                   annot.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                    self.enable_move_text_annot_mode()    # type: ignore

    def edit_annot_text(self, annot_text):
        annot, page = self.edited_annot_page
        if annot.parent:    # type: ignore
            if annot.type[0] == fitz.PDF_ANNOT_FREE_TEXT:    # type: ignore
                annot.set_info(content=annot_text)    # type: ignore
                point = annot.rect.top_left    # type: ignore
                fontsize = self.inline_text_annot_fontsize
                rect = self.compute_annot_rect_inline_text(point, fontsize, annot_text)
                annot.set_rect(rect)    # type: ignore
                message_to_emacs("Updated inline text annot!")
            else:
                annot.set_info(content=annot_text)    # type: ignore
                message_to_emacs("Updated annot!")
            annot.update()    # type: ignore
            self.save_annot()
        self.edited_annot_page = (None, None)

    def move_annot_text(self):
        annot, page = self.moved_annot_page
        if annot.parent:    # type: ignore
            if annot.type[0] == fitz.PDF_ANNOT_TEXT or annot.type[0] == fitz.PDF_ANNOT_FREE_TEXT:     # type: ignore
                (point, page_index) = self.move_text_annot_pos
                rect = annot.rect    # type: ignore
                new_rect = fitz.Rect(point, point.x + rect.width, point.y + rect.height)    # type: ignore
                annot.set_rect(new_rect)    # type: ignore
                annot.update()    # type: ignore
                self.save_annot()

        self.moved_annot_page = (None, None)
        self.disable_move_text_annot_mode()

    def hover_link(self):
        curtime = time.time()
        if curtime - self.scroll_wheel_lasttime <= 0.5:
            return None

        if self.is_move_text_annot_mode:
            return None

        ex, ey, page_index = self.get_cursor_absolute_position()
        if page_index is None or page_index >= self.document.page_count:
            return None

        page = self.document[page_index]

        is_hover_link = False
        current_link = None

        for link in page.get_links():
            if fitz.Point(ex, ey) in link["from"]:
                is_hover_link = True
                current_link = link
                break

        # update and print message only if changed
        if (is_hover_link != self.is_hover_link or
            (current_link is not None and current_link != self.last_hover_link)):

            if is_hover_link:
                QApplication.setOverrideCursor(Qt.CursorShape.PointingHandCursor)
            else:
                QApplication.setOverrideCursor(Qt.CursorShape.ArrowCursor)

            if current_link:
                self.last_hover_link = current_link
                if current_link != self.last_hover_link or not QToolTip.isVisible():
                    tooltip_text = ""
                    if uri := current_link.get("uri"):
                        tooltip_text = "Link to uri: " + str(uri)
                    elif page_num := current_link.get("page"):
                        tooltip_text = "Link to page: " + str(page_num + 1)

                    if tooltip_text != "":
                        QToolTip.showText(QCursor.pos(), tooltip_text,
                                          None, QRect(), 10000)
            else:
                if QToolTip.isVisible():
                    QToolTip.hideText()

            self.is_hover_link = is_hover_link

        return current_link

    def jump_to_page(self, page_num, pos_y=None):
        page_nume = int(page_num) - 1
        page_offset = max(self.scale * page_nume * self.page_height, 0)
        if pos_y == None:
            self.update_vertical_offset(min(page_offset, self.max_scroll_offset()))
        else:
            y_offset = self.scale * pos_y
            self.jump_to_offset(page_offset + y_offset)

    def jump_to_offset(self, offset):
        if (offset < self.scroll_offset + 0.15 * self.rect().height() or
            offset > self.scroll_offset + 0.85 * self.rect().height()):
            jump_offset = max(0, offset - 0.15 * self.rect().height())
            max_offset = self.scale * self.page_total_number * self.page_height - self.rect().height()
            if jump_offset < max_offset:
                self.update_vertical_offset(jump_offset)
            else:
                self.update_vertical_offset(max_offset)

    def jump_to_percent(self, percent):
        self.update_vertical_offset(min(max(self.scale * (self.page_total_number * self.page_height * percent / 100.0), 0), self.max_scroll_offset()))

    def jump_to_rect(self, page_index, rect):
        quad = rect.quad
        self.update_vertical_offset((page_index * self.page_height + quad.ul.y) * self.scale)

    def delete_pdf_page (self, page):
        self.document.delete_page(page)
        self.save_annot()

    def delete_pdf_pages (self, start_page, end_page):
        self.document.delete_pages(start_page, end_page)
        self.save_annot()

    def current_percent(self):
        return 100.0 * self.scroll_offset / (self.max_scroll_offset() + self.rect().height())

    def update_vertical_offset(self, new_offset):
        eval_in_emacs("eaf--clear-message", [])
        if self.scroll_offset != new_offset:
            self.scroll_offset = new_offset
            self.update()

            eval_in_emacs("eaf--pdf-update-position", [self.buffer_id,
                                                       self.current_page_index,
                                                       self.page_total_number])

    def update_horizontal_offset(self, new_offset):
        eval_in_emacs("eaf--clear-message", [])
        if self.horizontal_offset != new_offset:
            self.horizontal_offset = new_offset
            self.update()

    def get_cursor_absolute_position(self):
        pos = self.mapFromGlobal(QCursor.pos()) # map global coordinate to widget coordinate.
        ex, ey = pos.x(), pos.y()

        # set page coordinate
        render_width = self.page_width * self.scale
        render_height = self.page_height * self.scale
        render_x = int((self.rect().width() - render_width) / 2)
        if self.read_mode == "fit_to_customize" and render_width >= self.rect().width():
            render_x = max(min(render_x + self.horizontal_offset, 0), self.rect().width() - render_width)
        if (ex < render_x or ex > render_x + render_width or ey > render_height):
            return 0, 0, 0

        # computer absolute coordinate of page
        x = (ex - render_x) * 1.0 / self.scale
        if ey + self.scroll_offset < (self.start_page_index + 1) * self.scale * self.page_height:
            page_offset = self.scroll_offset - self.start_page_index * self.scale * self.page_height
            page_index = self.start_page_index
        else:
            # if display two pages, pos.y() will add page_padding
            page_offset = self.scroll_offset - (self.start_page_index + 1) * self.scale * self.page_height - self.page_padding
            page_index = self.start_page_index + 1
        y = (ey + page_offset) * 1.0 / self.scale

        temp = x
        if self.rotation == 90:
            x = y
            y = self.page_width - temp
        elif self.rotation == 180:
            x = self.page_width - x
            y = self.page_height - y
        elif self.rotation == 270:
            x = self.page_height - y
            y = temp

        return x, y, page_index

    def get_event_link(self):
        ex, ey, page_index = self.get_cursor_absolute_position()
        if page_index is None or page_index >= self.document.page_count:
            return None

        page = self.document[page_index]
        for link in page.get_links():
            rect = link["from"]
            if ex >= rect.x0 and ex <= rect.x1 and ey >= rect.y0 and ey <= rect.y1:
                return link

        return None

    def get_double_click_word(self):
        ex, ey, page_index = self.get_cursor_absolute_position()
        if page_index is None or page_index >= self.document.page_count:
            return None
        page = self.document[page_index]
        word_offset = 10 # 10 pixel is enough for word intersect operation
        draw_rect = fitz.Rect(ex, ey, ex + word_offset, ey + word_offset)

        set_page_crop_box(page)(page.rect)
        page_words = page.get_text_words()
        rect_words = [w for w in page_words if fitz.Rect(w[:4]).intersects(draw_rect)]
        if rect_words:
            return rect_words[0][4]

    def eventFilter(self, obj, event):
        if event.type() in [QEvent.Type.MouseButtonPress]:
            self.is_button_press = True
        elif event.type() in [QEvent.Type.MouseButtonRelease]:
            self.is_button_press = False

        if event.type() == QEvent.Type.MouseMove:
            if not self.is_rect_annot_mode:
                if self.hasMouseTracking():
                    self.hover_link()
                    self.check_annot()
                else:
                    self.handle_select_mode()

        elif event.type() == QEvent.Type.MouseButtonPress:
            # add this detect release mouse event
            self.grabMouse()

            # cleanup select mode on another click
            if self.is_select_mode:
                self.cleanup_select()

            if self.is_popup_text_annot_mode:
                if event.button() != Qt.MouseButton.LeftButton:
                    self.disable_popup_text_annot_mode()
            elif self.is_inline_text_annot_mode:
                if event.button() != Qt.MouseButton.LeftButton:
                    self.disable_inline_text_annot_mode()
            elif self.is_move_text_annot_mode:
                if event.button() != Qt.MouseButton.LeftButton:
                    self.disable_move_text_annot_mode()
            elif self.is_rect_annot_mode:
                if event.button() != Qt.MouseButton.LeftButton:
                    self.disable_rect_annot_mode()
                else:
                    self.handle_rect_annot_mode(True)
            else:
                modifiers = QApplication.keyboardModifiers()
                if event.button() == Qt.MouseButton.LeftButton:
                    # In order to catch mouse move event when drap mouse.
                    if self.is_hover_link:
                        if modifiers == Qt.KeyboardModifier.ControlModifier:
                            self.handle_click_link(True)
                        else:
                            self.handle_click_link(False)
                    else:
                        self.setMouseTracking(False)
                elif event.button() == Qt.MouseButton.RightButton:
                    self.handle_click_link(True)
                elif event.button() == Qt.MouseButton.MiddleButton:
                    self.save_current_pos()
                elif event.button() == Qt.MouseButton.ForwardButton:
                    self.jump_to_next_saved_pos()
                elif event.button() == Qt.MouseButton.BackButton:
                    self.jump_to_previous_saved_pos()

        elif event.type() == QEvent.Type.MouseButtonRelease:
            # Capture move event, event without holding down the mouse.
            self.setMouseTracking(True)
            self.releaseMouse()

            if self.is_rect_annot_mode:
                self.handle_rect_annot_mode(False)

            if not self.popup_text_annot_timer.isActive() and \
               self.is_popup_text_annot_handler_waiting:
                self.popup_text_annot_timer.start()

            if not self.inline_text_annot_timer.isActive() and \
               self.is_inline_text_annot_handler_waiting:
                self.inline_text_annot_timer.start()

            if not self.move_text_annot_timer.isActive() and \
               self.is_move_text_annot_handler_waiting:
                self.move_text_annot_timer.start()

            import platform
            if platform.system() == "Darwin":
                eval_in_emacs('eaf-activate-emacs-window', [])

        elif event.type() == QEvent.Type.MouseButtonDblClick:
            self.disable_popup_text_annot_mode()
            self.disable_inline_text_annot_mode()
            if event.button() == Qt.MouseButton.RightButton and self.document.is_pdf:
                self.handle_translate_word()
            elif event.button() == Qt.MouseButton.LeftButton:
                self.handle_synctex_backward_edit()
                return True

        return False

    def enable_popup_text_annot_mode(self):
        self.is_popup_text_annot_mode = True
        self.is_popup_text_annot_handler_waiting = True
        self.popup_text_annot_pos = (None, None)

    def disable_popup_text_annot_mode(self):
        self.is_popup_text_annot_mode = False
        self.is_popup_text_annot_handler_waiting = False

    @PostGui()
    def handle_popup_text_annot_mode(self):
        if self.is_popup_text_annot_mode:
            self.is_popup_text_annot_handler_waiting = False
            ex, ey, page_index = self.get_cursor_absolute_position()
            if page_index is None or page_index >= self.document.page_count:
                return
            self.popup_text_annot_pos = (fitz.Point(ex, ey), page_index)
            atomic_edit(self.buffer_id, "")

    def enable_inline_text_annot_mode(self):
        self.is_inline_text_annot_mode = True
        self.is_inline_text_annot_handler_waiting = True
        self.inline_text_annot_pos = (None, None)

    def disable_inline_text_annot_mode(self):
        self.is_inline_text_annot_mode = False
        self.is_inline_text_annot_handler_waiting = False

    @PostGui()
    def handle_inline_text_annot_mode(self):
        if self.is_inline_text_annot_mode:
            self.is_inline_text_annot_handler_waiting = False
            ex, ey, page_index = self.get_cursor_absolute_position()
            if page_index is None or page_index >= self.document.page_count:
                return
            self.inline_text_annot_pos = (fitz.Point(ex, ey), page_index)
            atomic_edit(self.buffer_id, "")

    def enable_rect_annot_mode(self):
        self.is_rect_annot_mode = True

    def disable_rect_annot_mode(self):
        self.is_rect_annot_mode = False

    def handle_rect_annot_mode(self, start_press):
        if self.is_rect_annot_mode:
            if start_press:
                self.rect_annot_beg_ex, self.rect_annot_beg_ey, page_index = self.get_cursor_absolute_position()
                if page_index is None or page_index >= self.document.page_count:
                    return
            else:
                end_ex, end_ey, page_index = self.get_cursor_absolute_position()
                if page_index is None or page_index >= self.document.page_count:
                    return

                page = self.document[page_index]
                annot_rect = fitz.Rect(self.rect_annot_beg_ex, self.rect_annot_beg_ey, end_ex, end_ey)

                if annot_rect.is_empty or annot_rect.is_infinite:
                    return

                new_annot = page.add_rect_annot(annot_rect)
                new_annot.set_info(title=self.user_name)
                new_annot.parent = page

                annot_action = AnnotAction.create_annot_action("Add", page_index, new_annot)
                self.record_new_annot_action(annot_action)

                self.save_annot()
                self.disable_rect_annot_mode()

    def enable_move_text_annot_mode(self):
        self.is_move_text_annot_mode = True
        self.is_move_text_annot_handler_waiting = True
        self.move_text_annot_pos = (None, None)

    def disable_move_text_annot_mode(self):
        self.is_move_text_annot_mode = False
        self.is_move_text_annot_handler_waiting = False

    @PostGui()
    def handle_move_text_annot_mode(self):
        if self.is_move_text_annot_mode:
            self.is_move_text_annot_handler_waiting = False
            ex, ey, page_index = self.get_cursor_absolute_position()
            if page_index is None or page_index >= self.document.page_count:
                return
            self.move_text_annot_pos = (fitz.Point(ex, ey), page_index)
            self.move_annot_text()

    def handle_select_mode(self):
        self.is_select_mode = True
        ex, ey, page_index = self.get_cursor_absolute_position()
        if page_index is None or page_index >= self.document.page_count:
            return
        rect_index = self.document[page_index].get_page_char_rect_index(ex, ey)
        if rect_index:
            if self.start_char_rect_index is None or self.start_char_page_index is None:
                self.start_char_rect_index, self.start_char_page_index = rect_index, page_index
            else:
                self.last_char_rect_index, self.last_char_page_index = rect_index, page_index
                self.update()

    def handle_click_link(self, external_browser=False):
        event_link = self.get_event_link()
        if event_link:
            self.handle_jump_to_link(event_link, external_browser)

    def handle_translate_word(self):
        double_click_word = self.get_double_click_word()
        if double_click_word:
            self.translate_double_click_word.emit(double_click_word)

    def handle_synctex_backward_edit(self):
        ex, ey, page_index = self.get_cursor_absolute_position()
        if page_index is None or page_index >= self.document.page_count:
            return
        folder = Path(self.url).parent
        # chech if ".synctex.gz" file exist
        file_name_without_ext = Path(self.url).stem
        synctex_gz = Path(file_name_without_ext + ".synctex.gz")
        synctex_file = folder / synctex_gz

        if os.path.exists(synctex_file) and self.document.is_pdf:
            eval_in_emacs("eaf-pdf-synctex-backward-edit", [self.url, page_index + 1, ex, ey])
        else:
            page_text = self.buffer.get_page_text(page_index)
            total_lines = len(page_text.splitlines())
            line_number = int((ey / self.page_height) * total_lines) # roughly
            eval_in_emacs("eaf-pdf-extract-page-text", [page_text, line_number])

    def edit_outline_confirm(self, payload):
        self.document.set_toc(payload)
        self.document.saveIncr()
        message_to_emacs("Updated PDF Table of Contents successfully.")

    def build_reverse_index(self):
        return self.document.build_reverse_index()


    def words_to_3d(self, words):
        array_3d = []
        for word in words:
            block_no, line_no, _ = word[5], word[6], word[7]
            while len(array_3d) <= block_no:
                array_3d.append([])
            while len(array_3d[block_no]) <= line_no:
                array_3d[block_no].append([])
            array_3d[block_no][line_no].append(word)
        return array_3d

    def get_page_words(self):
        page = self.document[self.current_page_index - 1]
        self.current_page_words = self.words_to_3d(page.get_text('words'))
        self.current_page_word_position = (0, 0, 0)


    def _move_word_by_block_offset(self, offset):
        block_no, line_no, word_no = self.current_page_word_position
        block_no = block_no + offset
        num_blocks = len(self.current_page_words)
        if block_no < 0:
            # previous page
            self.current_page_index -= 1
            if self.current_page_index < 1:
                return
            self.jump_to_page(self.current_page_index)
            # self.update()
            # time.sleep(0.2)
            print(self.current_page_index)
            self.get_page_words()
            block_no = len(self.current_page_words) - 1
            line_no = len(self.current_page_words[block_no]) - 1
            word_no = len(self.current_page_words[block_no][line_no]) - 1

        elif block_no >= num_blocks:
            # next page
            self.current_page_index += 1
            if self.current_page_index > self.page_total_number:
                return
            self.jump_to_page(self.current_page_index)
            # self.update()
            # time.sleep(0.2)
            print(self.current_page_index)
            self.get_page_words()
            block_no, line_no, word_no = 0, 0, 0

        self.current_page_word_position = block_no, line_no, word_no

    def _move_word_by_line_offset(self, offset):
        block_no, line_no, word_no = self.current_page_word_position
        line_no = line_no + offset
        num_lines = len(self.current_page_words[block_no])

        if line_no < 0:
            self._move_word_by_block_offset(-1)
            block_no, _, _ = self.current_page_word_position
            line_no = len(self.current_page_words[block_no])-1
            word_no = len(self.current_page_words[block_no][line_no])-1
        elif line_no >= num_lines:
            self._move_word_by_block_offset(1)
            block_no, _, _ = self.current_page_word_position
            line_no = 0
            word_no = 0

        self.current_page_word_position = block_no, line_no, word_no

    def _move_word_by_word_offset(self, offset):
        block_no, line_no, word_no = self.current_page_word_position
        word_no = word_no + offset
        num_words = len(self.current_page_words[block_no][line_no])

        if word_no < 0:
            self._move_word_by_line_offset(-1)
            block_no, line_no, _ = self.current_page_word_position
            word_no = len(self.current_page_words[block_no][line_no])-1
        elif word_no >= num_words:
            self._move_word_by_line_offset(1)
            block_no, line_no, _ = self.current_page_word_position
            word_no = 0

        self.current_page_word_position = block_no, line_no, word_no

    def move_current_page_word(self, block_offset, line_offset, word_offset, expand=False):
        if not self.current_page_words:
            self.get_page_words()
        self._move_word_by_block_offset(block_offset)
        self._move_word_by_line_offset(line_offset)
        self._move_word_by_word_offset(word_offset)

        (block_no, line_no, word_no) = self.current_page_word_position
        word = self.current_page_words[block_no][line_no][word_no]
        self.keyboard_select_text(word, expand)

    def selected_text(self):
        return " ".join([" ".join([word[4] for word in words]) for words in self.select_text_words_list])


    def selected_text_add_annot_of_action(self):
        page = self.document[self.current_page_index - 1]
        for quads in self.select_text_quads_list:
            new_annot = page.add_squiggly_annot(quads)
            annot_action = AnnotAction.create_annot_action("Add", self.current_page_index, new_annot)
            self.add_annot_of_action(annot_action)

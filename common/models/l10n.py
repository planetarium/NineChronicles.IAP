# NOTE:
#  Language is currently managed by hard-coded string.
#  Current languages are:
#    English
#    Korean
#    Portuguese
#    Japanese
#    ChineseSimplified
#    Thai
#    Spanish
#    Indonesian
#    Russian
#    ChineseTraditional
#    Tagalog

# TODO: Change languages from string to table
# from sqlalchemy import Column, Text
#
# from common.models.base import Base, TimeStampMixin, AutoIdMixin
#
#
# class Language(AutoIdMixin, TimeStampMixin, Base):
#     __tablename__ = "language"
#     code = Column(Text, nullable=False, index=True, doc="Language code of ISO 639-1")
#     name = Column(Text, nullable=False, doc="Language Name")

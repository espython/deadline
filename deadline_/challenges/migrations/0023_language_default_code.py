# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-05-22 18:32
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('challenges', '0022_auto_20170520_0634'),
    ]

    operations = [
        migrations.AddField(
            model_name='language',
            name='default_code',
            field=models.CharField(default='tank', max_length=200),
            preserve_default=False,
        ),
    ]
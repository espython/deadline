# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-06-02 10:00
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('challenges', '0031_auto_20170602_0958'),
    ]

    operations = [
        migrations.AlterField(
            model_name='language',
            name='name',
            field=models.CharField(max_length=30, unique=True),
        ),
        migrations.AlterField(
            model_name='submission',
            name='language',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='challenges.Language', to_field='id'),
        ),
    ]

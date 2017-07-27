# -*- coding: utf-8 -*-
# Generated by Django 1.10.5 on 2017-03-10 11:14
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('challenges', '0018_auto_20170310_1111'),
    ]

    operations = [
        migrations.CreateModel(
            name='Language',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=30, serialize=False, unique=True)),
            ],
        ),
        migrations.AddField(
            model_name='submission',
            name='language',
            field=models.ForeignKey(to='challenges.Language', to_field='id'),
            preserve_default=False,
        ),
    ]
